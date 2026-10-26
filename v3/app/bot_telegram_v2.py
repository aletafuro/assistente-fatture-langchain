"""
IL BOT TELEGRAM DELLA V2
========================

Stesso bot della v1 (stessi comandi, utenti autorizzati, download, trascrizione, avvisi, controllo
giornaliero delle scadenze): ne riusa le funzioni. Cambia SOLO a chi passa il messaggio.

   v1:  ogni messaggio  ->  agente (create_agent, che gestiva anche le bozze)

   v2:  foto / PDF / vocale / dati di una fattura     ->  GRAFO delle bozze (percorso fisso)
        risposta a una domanda del grafo              ->  il GRAFO riparte da dove si era fermato
        tutto il resto ("quanto ho speso?", "ho pagato") ->  AGENTE v2 (tool via MCP + RAG)

Il grafo e la memoria dell'agente stanno su SQLite: una domanda del grafo resta in sospeso anche
se il bot viene riavviato, e l'utente può rispondere quando vuole.

Avvio (dalla cartella del progetto):   python codice_v2/bot_telegram_v2.py
ATTENZIONE: v1 e v2 usano lo stesso bot Telegram: NON vanno accese insieme (Telegram consegna
i messaggi a una sola copia). Fermare la v1 prima di avviare la v2, e viceversa.
"""

import asyncio
from datetime import time as dt_time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import percorsi_v2  # noqa: F401

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import agente_v2
import anagrafica_esteri
import avvisi
import bot_telegram as v1          # riuso: autorizzazione, download, comandi /stato /controllo, errori
import grafo_bozze
import raccolta_mese
from registro_fatture import ErroreRegistro
from trascrizione import ErroreTrascrizione, trascrivi

log = v1.log


async def invia(update: Update, testo: str) -> None:
    for inizio in range(0, len(testo), v1.LIMITE_TELEGRAM):
        await update.message.reply_text(testo[inizio:inizio + v1.LIMITE_TELEGRAM])


# ---------------------------------------------------------------------------
# LO SMISTAMENTO
# ---------------------------------------------------------------------------

async def al_grafo(update: Update, funzione, *argomenti) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        risposta = await asyncio.to_thread(funzione, str(update.effective_chat.id), *argomenti)
    except ErroreRegistro as errore:
        risposta = f"⚠️ {errore} Ho già mandato un avviso tecnico."
    except Exception as errore:
        log.exception("Errore del grafo")
        avvisi.errore_tecnico("Grafo bozze (OpenAI)", errore)
        risposta = "Scusa, ho avuto un problema tecnico. La fattura in lavorazione non è andata persa: riprova tra poco."
    await invia(update, risposta)


async def all_agente(update: Update, messaggio: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    file_creati = []
    try:
        risposta, file_creati = await agente_v2.chiedi(messaggio, str(update.effective_chat.id))
    except ErroreRegistro as errore:
        risposta = f"⚠️ {errore} Ho già mandato un avviso tecnico."
    except Exception as errore:
        log.exception("Errore dell'agente")
        avvisi.errore_tecnico("Assistente v2 (OpenAI)", errore)
        risposta = "Scusa, ho avuto un problema tecnico nel rispondere. Riprova tra qualche minuto."
    await invia(update, risposta)
    for percorso in file_creati:
        if percorso.exists():
            with open(percorso, "rb") as f:
                await update.message.reply_document(f, filename=percorso.name)


async def elabora_raccolta(update: Update) -> None:
    """Il mese raccolto in chat viene elaborato e i file tornano in chat."""
    chat = str(update.effective_chat.id)
    await invia(update, "Elaboro le fatture del mese: può volerci qualche minuto (le fatture già lette "
                        "non si rileggono).")
    await update.effective_chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        messaggio, creati = await asyncio.to_thread(raccolta_mese.elabora, chat)
    except Exception as errore:
        log.exception("Elaborazione del mese")
        avvisi.errore_tecnico("Elaborazione del mese", errore)
        await invia(update, "Scusa, l'elaborazione non è riuscita. La raccolta resta aperta: riprova con \"elabora\".")
        return
    await invia(update, messaggio)
    for percorso in creati:
        with open(percorso, "rb") as f:
            await update.message.reply_document(f, filename=percorso.name)


async def smista_testo(update: Update, testo: str, percorso_audio: Path = None) -> None:
    chat = str(update.effective_chat.id)
    if raccolta_mese.aperta(chat):                            # raccolta del mese in corso
        comando = testo.strip().lower().rstrip(".!")
        if comando in ("elabora", "fatto", "ho finito", "finito"):
            await elabora_raccolta(update)
            return
        if comando in ("annulla", "annulla raccolta", "chiudi"):
            raccolta_mese.chiudi(chat)
            await invia(update, "Raccolta del mese annullata: non ho elaborato niente.")
            return
    if grafo_bozze.bozza_aperta(chat):                        # risposta a una domanda del grafo
        await al_grafo(update, grafo_bozze.rispondi, testo)
    elif await asyncio.to_thread(agente_v2.e_nuova_fattura, testo):   # ROUTER: fattura nuova?
        await al_grafo(update, lambda c, t, p: grafo_bozze.avvia(c, percorso=p, testo=t), testo, percorso_audio)
    else:
        await all_agente(update, testo)


async def nuovo_file(update: Update, percorso: Path, nome_originale: str = None) -> None:
    chat = str(update.effective_chat.id)
    if raccolta_mese.aperta(chat):                            # durante /mese i file vanno nella raccolta
        await invia(update, await asyncio.to_thread(raccolta_mese.aggiungi, chat, percorso,
                                                    nome_originale or percorso.name))
        return
    if grafo_bozze.bozza_aperta(chat):
        await invia(update, "Ho già una fattura in lavorazione: rispondi prima alla mia ultima domanda "
                            "(oppure scrivi \"annulla\"), poi rimandami questo file.")
        return
    nota = update.message.caption              # testo scritto insieme al file: completa i dati mancanti
    await al_grafo(update, lambda c, p, n: grafo_bozze.avvia(c, percorso=p, nota_utente=n), str(percorso), nota)


# ---------------------------------------------------------------------------
# GLI HANDLER
# ---------------------------------------------------------------------------

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await v1.autorizzato(update):
        return
    testo = ("Ciao! Sono il tuo assistente per le fatture fornitori (versione 3).\n"
             "Mandami una fattura come PDF, foto (meglio come file), vocale (numeri cifra per cifra) o testo:\n"
             "ti guiderò passo passo fino alla registrazione.\n"
             "Puoi anche chiedermi riepiloghi, scadenze, cosa hai comprato, o dirmi che hai pagato una fattura.\n"
             "Ogni fattura confermata va nello scadenziario (se è attivo); /scadenze mostra cosa pagare a breve, "
             "/saldata Fornitore numero la segna come pagata.\n"
             "Per la registrazione del mese: /registra ottobre elabora la cartella condivisa del mese "
             "(oppure /mese per mandarmi le fatture qui in chat).")
    domanda = grafo_bozze.domanda_in_sospeso(str(update.effective_chat.id))
    if domanda:
        testo += f"\n\nHai una fattura in sospeso. La mia ultima domanda era:\n{domanda}"
    await invia(update, testo)


async def comando_mese(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mese: si apre la raccolta delle fatture del mese (più gli estratti conto Amex e UniCredit)."""
    if not await v1.autorizzato(update):
        return
    raccolta_mese.apri(str(update.effective_chat.id))
    await invia(update, "Raccolta del mese aperta. Mandami le fatture (PDF o foto, anche tutte insieme o in uno ZIP) "
                        "e gli estratti conto (Excel Amex, PDF della carta UniCredit): li riconosco da solo.\n"
                        "Quando hai finito scrivi \"elabora\". Per lasciar perdere scrivi \"annulla\".")


async def comando_registra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/registra ottobre: elabora il blocco messo nella cartella condivisa; i risultati restano lì."""
    if not await v1.autorizzato(update):
        return
    testo = " ".join(context.args)
    cartella = raccolta_mese.trova_cartella_mese(testo) if testo else None
    if cartella is None:
        await invia(update, "Dimmi il mese della cartella, es. \"/registra ottobre\" o \"/registra 10 Ottobre\".")
        return
    await invia(update, f"Elaboro la cartella \"{cartella.name}\": può volerci qualche minuto.")
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        messaggio, _ = await asyncio.to_thread(raccolta_mese.elabora_cartella, cartella)
    except Exception as errore:
        log.exception("Registrazione del mese")
        avvisi.errore_tecnico("Registrazione del mese", errore)
        messaggio = "Scusa, l'elaborazione non è riuscita: riprova tra poco."
    await invia(update, messaggio)


async def comando_saldata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/saldata Fornitore [numero]: nello scadenziario la fattura diventa "saldata"."""
    if not await v1.autorizzato(update):
        return
    import scadenziario
    if not context.args:
        await invia(update, "Scrivi \"/saldata Fornitore numero\", es. \"/saldata Contoso 2026/15\".")
        return
    # L'ultima parola è il numero se contiene una cifra; il resto è il fornitore.
    *nome, ultima = context.args
    numero = ultima if nome and any(c.isdigit() for c in ultima) else None
    fornitore = " ".join(nome if numero else context.args)
    await invia(update, await asyncio.to_thread(scadenziario.segna_saldata, fornitore, numero))


async def comando_scadenze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/scadenze: fatture ancora da pagare nello scadenziario, entro i prossimi 15 giorni."""
    if not await v1.autorizzato(update):
        return
    import scadenziario
    from datetime import date, timedelta
    righe = await asyncio.to_thread(scadenziario.da_pagare, (date.today() + timedelta(days=15)).isoformat())
    if not righe:
        await invia(update, "Nessuna fattura da pagare nei prossimi 15 giorni.")
        return
    await invia(update, "Da pagare entro 15 giorni:\n" + "\n".join(
        f"- {scadenziario._giorno(r['Data di Scadenza']):%d/%m} {r['Fornitore']} n. {r['Numero Fattura']}: "
        f"{r['Importo EURO'] or '?'} €" + (f" ({r['Rata']})" if r["Rata"] else "") for r in righe))


def testo_per_il_bot(update: Update, nome_bot: str, id_bot: int) -> Optional[str]:
    """
    In chat privata ogni messaggio è per il bot. Nel GRUPPO no: le persone si scrivono anche tra loro.
    Il bot risponde se lo si nomina (@nome), se si risponde a un suo messaggio, o se c'è una sua domanda
    (o la raccolta del mese) in corso. Altrimenti None: il messaggio si ignora.
    """
    testo = update.message.text or ""
    if not v1.in_gruppo(update):
        return testo
    chat = str(update.effective_chat.id)
    menzione = f"@{nome_bot}".lower() if nome_bot else None
    if menzione and menzione in testo.lower():
        inizio = testo.lower().index(menzione)
        return (testo[:inizio] + testo[inizio + len(menzione):]).strip()
    risposta_a = update.message.reply_to_message
    if risposta_a and risposta_a.from_user and risposta_a.from_user.id == id_bot:
        return testo
    if raccolta_mese.aperta(chat) or grafo_bozze.bozza_aperta(chat):
        return testo
    return None


async def messaggio_testo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    testo = testo_per_il_bot(update, context.bot.username, context.bot.id)
    if testo and await v1.autorizzato(update):
        await smista_testo(update, testo)


async def messaggio_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await v1.autorizzato(update):
        percorso = await v1.scarica(await update.message.photo[-1].get_file(), "foto.jpg", update)
        await nuovo_file(update, percorso)


async def messaggio_documento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await v1.autorizzato(update):
        return
    documento = update.message.document
    nome = documento.file_name or "documento"
    ammessi = raccolta_mese.ESTENSIONI if raccolta_mese.aperta(str(update.effective_chat.id)) else v1.ESTENSIONI_DOCUMENTI
    if Path(nome).suffix.lower() not in ammessi:
        await invia(update, f"Il file '{nome}' non è in un formato che so leggere. Mandami un PDF, una foto "
                            "JPG/PNG, un vocale oppure scrivimi i dati.")
        return
    if documento.file_size and documento.file_size > 20 * 1024 * 1024:
        await invia(update, "Il file è troppo grande (limite di Telegram per i bot: 20 MB).")
        return
    await nuovo_file(update, await v1.scarica(await documento.get_file(), nome, update), nome)


async def messaggio_vocale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await v1.autorizzato(update):
        return
    audio = update.message.voice or update.message.audio
    estensione = Path(getattr(audio, "file_name", None) or "vocale.ogg").suffix or ".ogg"
    percorso = await v1.scarica(await audio.get_file(), f"vocale{estensione}", update)
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        testo = await asyncio.to_thread(trascrivi, percorso)
    except ErroreTrascrizione as errore:
        await invia(update, str(errore))
        return
    await invia(update, f"Ho capito: \"{testo}\"")
    await smista_testo(update, testo, percorso_audio=percorso)


# ---------------------------------------------------------------------------
# AVVIO
# ---------------------------------------------------------------------------

async def controllo_anagrafica(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ogni mese: dati ufficiali dei fornitori esteri confrontati con il mese prima -> avviso con le modifiche."""
    try:
        testo = await asyncio.to_thread(anagrafica_esteri.controllo_mensile)
        await asyncio.to_thread(avvisi.notifica, "Anagrafica fornitori esteri", testo)
    except Exception as errore:
        log.exception("Controllo anagrafica")
        avvisi.errore_tecnico("Controllo anagrafica fornitori esteri", errore)


async def comando_anagrafica(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/anagrafica: controllo subito sui registri ufficiali + file Excel con anagrafica e storico."""
    if not await v1.autorizzato(update):
        return
    await invia(update, "Controllo i fornitori esteri sui registri ufficiali: può volerci qualche minuto...")
    testo = await asyncio.to_thread(anagrafica_esteri.controllo_mensile)
    await invia(update, testo)
    percorso = await asyncio.to_thread(anagrafica_esteri.esporta_excel)
    with open(percorso, "rb") as f:
        await update.message.reply_document(f, filename=percorso.name)


async def all_avvio(app: Application) -> None:
    strumenti = await agente_v2.prepara()
    print(f"Agente v2 pronto. Tool dal server MCP: {', '.join(strumenti)}")


async def alla_chiusura(app: Application) -> None:
    await agente_v2.chiudi()


def main() -> None:
    if not v1.TOKEN:
        print("Manca TELEGRAM_BOT_TOKEN nel file .env (vedi .env.example).")
        return
    app = (Application.builder().token(v1.TOKEN)
           .post_init(all_avvio).post_shutdown(alla_chiusura).build())
    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("stato", v1.comando_stato))
    app.add_handler(CommandHandler("controllo", v1.comando_controllo))
    app.add_handler(CommandHandler("anagrafica", comando_anagrafica))
    app.add_handler(CommandHandler("mese", comando_mese))
    app.add_handler(CommandHandler("registra", comando_registra))
    app.add_handler(CommandHandler("saldata", comando_saldata))
    app.add_handler(CommandHandler("scadenze", comando_scadenze))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messaggio_testo))
    app.add_handler(MessageHandler(filters.PHOTO, messaggio_foto))
    app.add_handler(MessageHandler(filters.Document.ALL, messaggio_documento))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, messaggio_vocale))
    app.add_error_handler(v1.gestisci_errore)
    ore, minuti = (int(x) for x in avvisi.configurazione()["ora_controllo"].split(":"))
    app.job_queue.run_daily(v1.controllo_giornaliero, time=dt_time(ore, minuti, tzinfo=ZoneInfo("Europe/Rome")))
    # Il primo giorno di ogni mese: controllo dell'anagrafica dei fornitori esteri sui registri ufficiali.
    app.job_queue.run_monthly(controllo_anagrafica, when=dt_time(ore, minuti, tzinfo=ZoneInfo("Europe/Rome")), day=1)
    print(f"Bot v2 avviato (controllo scadenze alle {ore:02d}:{minuti:02d}). Ctrl+C per fermarlo.")
    app.run_polling()


if __name__ == "__main__":
    main()
