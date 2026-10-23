"""
AVVISI CONFIGURABILI (funzione 8)
================================================

"Avvisi tecnici configurabili: soglie, destinatari o canali parametrizzabili, NON cablati nel codice."
Quindi TUTTO quello che si può voler cambiare sta nel file .env, non qui:

   AVVISI_CANALI=telegram,email          -> dove mandare gli avvisi (telegram, email, oppure solo log)
   AVVISI_TELEGRAM_CHAT_ID=123456789    -> chi li riceve su Telegram (anche più id, separati da virgola)
   AVVISI_EMAIL=nome@esempio.it          -> chi li riceve via email (anche più indirizzi)
   AVVISI_SOGLIA_IMPORTO_EURO=5000       -> avvisa quando si registra una fattura da almeno questo importo
   AVVISI_GIORNI_SCADENZA=7              -> nel controllo giornaliero, scadenze entro quanti giorni
   AVVISI_ORA_CONTROLLO=09:00            -> a che ora fare il controllo giornaliero
   AVVISI_ERRORI_SOGLIA=3                -> dopo quanti errori dello stesso servizio mandare l'avviso tecnico
   AVVISI_ERRORI_FINESTRA_MINUTI=15      -> ...in quanti minuti
   AVVISI_PAUSA_MINUTI=60                -> dopo un avviso, silenzio per quel servizio (niente raffiche)

Due famiglie di avvisi:
   TECNICI  -> un servizio esterno (OpenAI, Google Drive, Gmail) non risponde più volte di seguito
   CONTABILI -> fattura sopra soglia, scadenze in arrivo / scadute

Tutti gli errori, anche quelli che non fanno scattare un avviso, finiscono in log/errori.log.

Gli avvisi partono con una semplice richiesta HTTP all'API di Telegram (non serve il bot acceso)
e con Gmail (google_servizi.invia_email). Se l'invio di un avviso fallisce... lo scriviamo nel log:
un avviso non deve MAI far bloccare il programma.
"""

import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta

import httpx

import config

# --- log su file ---
log = logging.getLogger("avvisi")
if not log.handlers:
    gestore = logging.FileHandler(config.LOG / "errori.log", encoding="utf-8")
    gestore.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(gestore)
    log.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# CONFIGURAZIONE (tutta dal .env, con valori predefiniti ragionevoli)
# ---------------------------------------------------------------------------

def _lista(nome: str) -> list:
    return [x.strip() for x in os.getenv(nome, "").split(",") if x.strip()]


def _numero(nome: str, predefinito: float) -> float:
    try:
        return float(os.getenv(nome, predefinito))
    except ValueError:
        log.warning("Valore non valido per %s nel .env: uso %s", nome, predefinito)
        return predefinito


def configurazione() -> dict:
    return {
        "canali": _lista("AVVISI_CANALI") or ["log"],
        "telegram": _lista("AVVISI_TELEGRAM_CHAT_ID"),
        "email": _lista("AVVISI_EMAIL"),
        "soglia_importo_cent": int(_numero("AVVISI_SOGLIA_IMPORTO_EURO", 5000) * 100),
        "giorni_scadenza": int(_numero("AVVISI_GIORNI_SCADENZA", 7)),
        "ora_controllo": os.getenv("AVVISI_ORA_CONTROLLO", "09:00"),
        "errori_soglia": int(_numero("AVVISI_ERRORI_SOGLIA", 3)),
        "errori_finestra": timedelta(minutes=_numero("AVVISI_ERRORI_FINESTRA_MINUTI", 15)),
        "pausa": timedelta(minutes=_numero("AVVISI_PAUSA_MINUTI", 60)),
    }


# ---------------------------------------------------------------------------
# INVIO DI UN AVVISO SUI CANALI CONFIGURATI
# ---------------------------------------------------------------------------

def notifica(titolo: str, testo: str) -> list:
    """Manda l'avviso su tutti i canali configurati. Restituisce dove è stato mandato."""
    conf = configurazione()
    inviato_a = []
    log.info("AVVISO %s | %s", titolo, testo.replace("\n", " / "))

    if "telegram" in conf["canali"]:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        for chat_id in conf["telegram"]:
            try:
                httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": chat_id, "text": f"⚠️ {titolo}\n\n{testo}"}, timeout=10).raise_for_status()
                inviato_a.append(f"telegram:{chat_id}")
            except Exception as errore:
                log.error("Avviso Telegram non inviato a %s: %s", chat_id, type(errore).__name__)

    if "email" in conf["canali"]:
        from google_servizi import invia_email      # importato qui: serve solo se il canale è attivo
        for indirizzo in conf["email"]:
            try:
                invia_email(indirizzo, f"[Assistente fatture] {titolo}", testo, segnala_errori=False)
                inviato_a.append(f"email:{indirizzo}")
            except Exception as errore:
                log.error("Avviso email non inviato a %s: %s", indirizzo, type(errore).__name__)
    return inviato_a


# ---------------------------------------------------------------------------
# AVVISI TECNICI: errori ripetuti di un servizio esterno
# ---------------------------------------------------------------------------
# Un errore singolo può capitare (rete lenta): lo scriviamo nel log e basta.
# Se lo STESSO servizio sbaglia N volte in pochi minuti, c'è un problema vero: avvisiamo.
# Poi stiamo zitti per un po', per non mandare 50 messaggi uguali.

_errori_recenti = defaultdict(deque)   # servizio -> orari degli ultimi errori
_ultimo_avviso = {}                    # servizio -> orario dell'ultimo avviso mandato


def errore_tecnico(servizio: str, errore: Exception) -> bool:
    """Da chiamare quando un servizio esterno fallisce. Restituisce True se è partito un avviso."""
    conf = configurazione()
    adesso = datetime.now()
    log.error("ERRORE %s: %s: %s", servizio, type(errore).__name__, errore)

    recenti = _errori_recenti[servizio]
    recenti.append(adesso)
    while recenti and adesso - recenti[0] > conf["errori_finestra"]:
        recenti.popleft()

    in_pausa = servizio in _ultimo_avviso and adesso - _ultimo_avviso[servizio] < conf["pausa"]
    if len(recenti) >= conf["errori_soglia"] and not in_pausa:
        _ultimo_avviso[servizio] = adesso
        minuti = int(conf["errori_finestra"].total_seconds() // 60)
        notifica(f"Problema tecnico: {servizio}",
                 f"{len(recenti)} errori negli ultimi {minuti} minuti.\n"
                 f"Ultimo errore: {type(errore).__name__}.\n"
                 f"Le fatture già registrate sono al sicuro; le operazioni fallite si possono ripetere.")
        return True
    return False


# ---------------------------------------------------------------------------
# AVVISI CONTABILI
# ---------------------------------------------------------------------------

def controlla_importo(fattura: dict) -> str:
    """Da chiamare dopo la registrazione. Restituisce un testo di avviso ('' se sotto soglia)."""
    conf = configurazione()
    totale = fattura.get("totale_cent") or 0
    if totale < conf["soglia_importo_cent"]:
        return ""
    from registro_fatture import centesimi_in_euro
    testo = (f"Registrata la fattura {fattura['id']} di {fattura['fornitore']} (n. {fattura['numero']}) "
             f"da {centesimi_in_euro(totale)}, sopra la soglia di {centesimi_in_euro(conf['soglia_importo_cent'])}.")
    notifica("Fattura sopra soglia", testo)
    return testo


def controllo_scadenze() -> tuple:
    """Il controllo giornaliero: fatture in scadenza entro N giorni o già scadute.
    Restituisce (testo, destinatari a cui è stato mandato l'avviso)."""
    import registro_fatture as reg
    conf = configurazione()
    testo = reg.fatture_in_scadenza(conf["giorni_scadenza"])
    if "Nessuna fattura in scadenza" in testo and "senza data" not in testo:
        log.info("Controllo scadenze: niente da segnalare")
        return testo, []
    return testo, notifica(f"Scadenze entro {conf['giorni_scadenza']} giorni", testo)
