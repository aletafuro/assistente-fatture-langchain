"""
IL BOT TELEGRAM - punto di ingresso dell'assistente (acquisizione multicanale)
==============================================================================

Il bot NON è intelligente: è un "centralinista" che
   1) riceve il messaggio (testo, foto, PDF, vocale)
   2) se è un file, lo scarica nella cartella dati/ricevuti
   3) se è un vocale, lo trascrive in testo
   4) passa tutto all'AGENTE e rimanda indietro la risposta (e gli eventuali file creati)

   Telegram --> bot_telegram.py --> agente_fatture.py --> tool --> bozze / registro / Drive / Gmail

Avvio (dalla cartella del progetto):   python codice/bot_telegram.py
Serve il file .env (vedi .env.example). Il bot resta acceso finché non lo si ferma (Ctrl+C).

Concetti:
   - HANDLER: una funzione chiamata quando arriva un certo TIPO di messaggio
     (testo, foto, documento, vocale, comandi /start /stato /controllo).
   - async / await: il bot può ricevere messaggi mentre ne sta elaborando altri.
   - asyncio.to_thread: l'agente (lento e sincrono) gira in un thread separato, il bot resta reattivo.
   - JobQueue: il controllo giornaliero delle scadenze all'ora scelta nel .env.
"""

import asyncio
import logging
import os
from datetime import time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config

# ---------------------------------------------------------------------------
# CONFIGURAZIONE DAL FILE .env (caricato da config.py)
# ---------------------------------------------------------------------------
# Nel codice scriviamo os.getenv("TELEGRAM_BOT_TOKEN"): il token vero non compare mai.

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
UTENTI_AUTORIZZATI = {u.strip() for u in os.getenv("TELEGRAM_UTENTI_AUTORIZZATI", "").split(",") if u.strip()}

CARTELLA_RICEVUTI = config.RICEVUTI

ESTENSIONI_DOCUMENTI = {".pdf", ".jpg", ".jpeg", ".png"}
LIMITE_TELEGRAM = 4000     # Telegram accetta messaggi fino a 4096 caratteri

import avvisi
import bozze_fatture as boz
from agente_fatture import chiedi_all_agente_con_file
from registro_fatture import ErroreRegistro
from trascrizione import ErroreTrascrizione, trascrivi

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)   # meno "rumore" nel terminale
log = logging.getLogger("bot")


# ---------------------------------------------------------------------------
# SICUREZZA: chi può usare il bot?
# ---------------------------------------------------------------------------
# Un bot Telegram è raggiungibile da CHIUNQUE conosca il suo nome.
# Le fatture sono dati aziendali: rispondiamo solo agli utenti autorizzati nel .env.

async def autorizzato(update: Update) -> bool:
    id_utente = str(update.effective_user.id)
    if id_utente in UTENTI_AUTORIZZATI:
        return True
    log.warning("Messaggio da utente NON autorizzato: %s", id_utente)
    await update.message.reply_text(
        f"Non sei autorizzato a usare questo assistente.\n"
        f"Il tuo id Telegram è {id_utente}: se sei il proprietario, aggiungilo nel file .env "
        f"alla riga TELEGRAM_UTENTI_AUTORIZZATI e riavvia il bot.")
    return False


# ---------------------------------------------------------------------------
# IL PASSAGGIO ALL'AGENTE (usato da tutti gli handler)
# ---------------------------------------------------------------------------

async def rispondi_con_agente(update: Update, messaggio_per_agente: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)   # "sta scrivendo..."
    file_creati = []
    try:
        risposta, file_creati = await asyncio.to_thread(
            chiedi_all_agente_con_file, messaggio_per_agente, str(update.effective_chat.id))
    except ErroreRegistro as errore:
        risposta = f"⚠️ {errore} Ho già mandato un avviso tecnico."
    except Exception as errore:
        log.exception("Errore dell'agente")
        avvisi.errore_tecnico("Assistente (OpenAI)", errore)
        risposta = ("Scusa, ho avuto un problema tecnico nel rispondere (forse il servizio AI non è "
                    "raggiungibile). Riprova tra qualche minuto: le bozze già create non sono andate perse.")
    for inizio in range(0, len(risposta), LIMITE_TELEGRAM):     # messaggi lunghi -> più pezzi
        await update.message.reply_text(risposta[inizio:inizio + LIMITE_TELEGRAM])
    for percorso in file_creati:                                 # es. il file Excel del riepilogo
        if percorso.exists():
            with open(percorso, "rb") as file_da_mandare:
                await update.message.reply_document(file_da_mandare, filename=percorso.name)


async def scarica(file_telegram, nome: str, update: Update) -> Path:
    """Salva il file ricevuto con un nome unico: idchat_idmessaggio_nomeoriginale."""
    percorso = CARTELLA_RICEVUTI / f"{update.effective_chat.id}_{update.message.message_id}_{nome}"
    await file_telegram.download_to_drive(percorso)
    log.info("File salvato: %s", percorso.name)
    return percorso


# ---------------------------------------------------------------------------
# GLI HANDLER: uno per ogni tipo di messaggio
# ---------------------------------------------------------------------------

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await autorizzato(update):
        return
    testo = ("Ciao! Sono il tuo assistente per le fatture fornitori.\n"
             "Puoi mandarmi:\n"
             "- un PDF o una foto della fattura (meglio come FILE, per una qualità migliore)\n"
             "- un messaggio vocale con i dati dettati (partita IVA e numeri meglio cifra per cifra)\n"
             "- i dati scritti in un messaggio\n"
             "Puoi anche chiedermi riepiloghi, scadenze, o dirmi che hai pagato una fattura.")
    aperte = boz.elenca_bozze_aperte()
    if aperte != "Nessuna bozza aperta.":
        testo += f"\n\nHai delle bozze in sospeso:\n{aperte}"
    await update.message.reply_text(testo)


async def messaggio_testo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await autorizzato(update):
        return
    await rispondi_con_agente(update, update.message.text)


async def messaggio_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foto inviata come 'foto' (Telegram la comprime). Prendiamo la versione più grande: photo[-1]."""
    if not await autorizzato(update):
        return
    file_telegram = await update.message.photo[-1].get_file()
    percorso = await scarica(file_telegram, "foto.jpg", update)
    didascalia = f" Nota dell'utente: {update.message.caption}" if update.message.caption else ""
    await rispondi_con_agente(update, f"Ho ricevuto la foto di una fattura, salvata in: {percorso}.{didascalia}")


async def messaggio_documento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """File allegato (PDF, o foto inviata 'come file' senza compressione)."""
    if not await autorizzato(update):
        return
    documento = update.message.document
    nome = documento.file_name or "documento"
    if Path(nome).suffix.lower() not in ESTENSIONI_DOCUMENTI:
        await update.message.reply_text(
            f"Il file '{nome}' non è in un formato che so leggere. Mandami un PDF, una foto JPG/PNG, "
            "un vocale oppure scrivimi i dati.")
        return
    if documento.file_size and documento.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("Il file è troppo grande (limite di Telegram per i bot: 20 MB).")
        return
    percorso = await scarica(await documento.get_file(), nome, update)
    didascalia = f" Nota dell'utente: {update.message.caption}" if update.message.caption else ""
    await rispondi_con_agente(update, f"Ho ricevuto il file di una fattura, salvato in: {percorso}.{didascalia}")


async def messaggio_vocale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vocale (voice) o file audio (audio): prima trascriviamo, poi passiamo il TESTO all'agente."""
    if not await autorizzato(update):
        return
    audio = update.message.voice or update.message.audio
    estensione = Path(getattr(audio, "file_name", None) or "vocale.ogg").suffix or ".ogg"
    percorso = await scarica(await audio.get_file(), f"vocale{estensione}", update)

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        testo = await asyncio.to_thread(trascrivi, percorso)
    except ErroreTrascrizione as errore:
        await update.message.reply_text(str(errore))
        return
    await update.message.reply_text(f"Ho capito: \"{testo}\"")     # l'utente vede cosa è stato capito
    await rispondi_con_agente(update, f"[VOCALE TRASCRITTO] (file audio: {percorso}) {testo}")


# ---------------------------------------------------------------------------
# LEZIONE 7 - AVVISI: controllo giornaliero e comandi
# ---------------------------------------------------------------------------

async def controllo_giornaliero(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parte da solo ogni giorno all'ora AVVISI_ORA_CONTROLLO del .env (JobQueue)."""
    await asyncio.to_thread(avvisi.controllo_scadenze)


async def comando_controllo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/controllo = fai subito il controllo delle scadenze (utile per provarlo senza aspettare)."""
    if not await autorizzato(update):
        return
    testo, inviato_a = await asyncio.to_thread(avvisi.controllo_scadenze)
    if f"telegram:{update.effective_chat.id}" in inviato_a:
        # L'avviso è già arrivato in questa chat: non ripetiamo l'elenco.
        altri = [d for d in inviato_a if d != f"telegram:{update.effective_chat.id}"]
        await update.message.reply_text("Controllo scadenze fatto: l'avviso è qui sopra."
                                        + (f" Inviato anche a: {', '.join(altri)}." if altri else ""))
    elif inviato_a:
        await update.message.reply_text(f"Controllo scadenze fatto, avviso inviato a: {', '.join(inviato_a)}.\n\n{testo}"[:LIMITE_TELEGRAM])
    else:
        await update.message.reply_text(f"Controllo scadenze fatto, niente da segnalare.\n{testo}"[:LIMITE_TELEGRAM])


async def comando_stato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stato = mostra la configurazione degli avvisi (letta dal .env)."""
    if not await autorizzato(update):
        return
    conf = avvisi.configurazione()
    in_attesa = [f["id"] for f in __import__("registro_fatture").carica_registro() if f.get("archiviazione") == "in_attesa"]
    await update.message.reply_text(
        "Configurazione avvisi (dal file .env):\n"
        f"- canali: {', '.join(conf['canali'])}\n"
        f"- destinatari Telegram: {len(conf['telegram'])} - email: {', '.join(conf['email']) or 'nessuno'}\n"
        f"- soglia importo: {conf['soglia_importo_cent'] // 100} €\n"
        f"- controllo scadenze: ogni giorno alle {conf['ora_controllo']}, entro {conf['giorni_scadenza']} giorni\n"
        f"- avviso tecnico dopo {conf['errori_soglia']} errori in {int(conf['errori_finestra'].total_seconds() // 60)} minuti, "
        f"poi pausa di {int(conf['pausa'].total_seconds() // 60)} minuti\n"
        f"- originali in attesa di archiviazione su Drive: {', '.join(in_attesa) or 'nessuno'}")


async def gestisci_errore(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Qualsiasi errore imprevisto: lo scriviamo nel log e avvisiamo l'utente, SENZA fermare il bot."""
    log.error("Errore non gestito", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Si è verificato un errore imprevisto. Riprova, per favore.")


# ---------------------------------------------------------------------------
# AVVIO
# ---------------------------------------------------------------------------

def main() -> None:
    if not TOKEN:
        print("Manca TELEGRAM_BOT_TOKEN nel file .env (vedi .env.example).")
        return
    if not UTENTI_AUTORIZZATI:
        print("ATTENZIONE: TELEGRAM_UTENTI_AUTORIZZATI è vuoto nel .env: il bot risponderà a tutti "
              "'non autorizzato' e ti dirà il tuo id da inserire.")

    app = Application.builder().token(TOKEN).build()

    # Ogni handler ha un FILTRO che dice per quali messaggi scatta.
    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messaggio_testo))
    app.add_handler(MessageHandler(filters.PHOTO, messaggio_foto))
    app.add_handler(MessageHandler(filters.Document.ALL, messaggio_documento))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, messaggio_vocale))
    app.add_handler(CommandHandler("controllo", comando_controllo))
    app.add_handler(CommandHandler("stato", comando_stato))
    app.add_error_handler(gestisci_errore)

    # Controllo giornaliero delle scadenze, all'ora scelta nel .env.
    try:
        ore, minuti = (int(x) for x in avvisi.configurazione()["ora_controllo"].split(":"))
        app.job_queue.run_daily(controllo_giornaliero, time=dt_time(ore, minuti, tzinfo=ZoneInfo("Europe/Rome")))
        print(f"Controllo scadenze programmato ogni giorno alle {ore:02d}:{minuti:02d}.")
    except Exception as errore:
        print(f"ATTENZIONE: controllo giornaliero non programmato ({errore}). Controlla AVVISI_ORA_CONTROLLO nel .env.")

    print("Bot avviato. Scrivigli su Telegram! (Ctrl+C per fermarlo)")
    app.run_polling()      # "polling" = il bot chiede continuamente a Telegram: ci sono messaggi nuovi?


if __name__ == "__main__":
    main()
