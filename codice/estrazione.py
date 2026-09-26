"""
ESTRAZIONE DEI DATI DELLE FATTURE (PDF, foto, testo)
=========================================================

Tre canali: PDF (testo estratto con pypdf), foto (modello vision), TESTO libero (es. "fattura di Rossi, 500 euro più IVA...").
Il testo servirà anche per i messaggi vocali: prima li trascriviamo in testo
(trascrizione.py), poi usiamo questa stessa funzione.

Tutte e tre restituiscono lo stesso dizionario (importi in centesimi, date AAAA-MM-GG),
così il resto del programma non deve sapere da quale canale arriva la fattura.
"""

import base64
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

import avvisi
from fatture_comuni import ISTRUZIONI_ESTRAZIONE, DatiFattura, in_dizionario, leggi_pdf

FORMATI_IMMAGINE = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}

# Modelli scelti MISURANDO sul golden set (vedi valutazione/ e RELAZIONE).
_estrattore_testo = init_chat_model("openai:gpt-4o-mini", temperature=0).with_structured_output(DatiFattura)
_estrattore_foto = init_chat_model("openai:gpt-4.1-mini", temperature=0).with_structured_output(DatiFattura)

_chain_testo = ChatPromptTemplate.from_messages([
    ("system", ISTRUZIONI_ESTRAZIONE),
    ("human", "Testo della fattura:\n\n{testo}"),
]) | _estrattore_testo


class ErroreEstrazione(Exception):
    """Errore 'gentile': il messaggio si può mostrare così com'è all'utente."""


def _servizio_non_disponibile(errore: Exception) -> ErroreEstrazione:
    """OpenAI non risponde: lo registriamo per gli avvisi tecnici e diamo un messaggio chiaro."""
    avvisi.errore_tecnico("OpenAI (lettura fatture)", errore)
    return ErroreEstrazione("Il servizio che legge le fatture (OpenAI) al momento non risponde. "
                            "Riprova tra qualche minuto: non è andato perso niente.")


def estrai_da_testo(testo: str, nome: str = "testo") -> dict:
    try:
        return in_dizionario(nome, _chain_testo.invoke({"testo": testo}))
    except Exception as errore:
        raise _servizio_non_disponibile(errore)


def estrai_da_pdf(percorso: Path) -> dict:
    try:
        testo = leggi_pdf(percorso)
    except Exception:
        raise ErroreEstrazione(f"Non riesco ad aprire il PDF {percorso.name}: il file potrebbe essere danneggiato.")
    if not testo.strip():
        raise ErroreEstrazione(f"Il PDF {percorso.name} non contiene testo (forse è una scansione): "
                               "mandamelo come foto.")
    return estrai_da_testo(testo, percorso.name)


# Ogni formato di immagine inizia con dei byte fissi ("firma"): se non ci sono, il file è rotto
# o non è davvero un'immagine (es. un .docx rinominato in .jpg).
FIRME_IMMAGINE = {"jpeg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n"}


def estrai_da_foto(percorso: Path) -> dict:
    tipo = FORMATI_IMMAGINE[percorso.suffix.lower()]
    contenuto = percorso.read_bytes()
    if not contenuto.startswith(FIRME_IMMAGINE[tipo]):
        raise ErroreEstrazione(f"Il file {percorso.name} non è un'immagine valida o è danneggiato.")
    immagine = base64.b64encode(contenuto).decode("utf-8")
    messaggi = [
        SystemMessage(content=ISTRUZIONI_ESTRAZIONE),
        HumanMessage(content=[
            {"type": "text", "text": "Estrai i dati da questa foto di una fattura."},
            {"type": "image_url", "image_url": {"url": f"data:image/{tipo};base64,{immagine}", "detail": "high"}},
        ]),
    ]
    try:
        return in_dizionario(percorso.name, _estrattore_foto.invoke(messaggi))
    except Exception as errore:
        raise _servizio_non_disponibile(errore)


def estrai_da_file(percorso: Path) -> dict:
    """Sceglie da solo il metodo giusto guardando l'estensione del file."""
    percorso = Path(percorso)
    if not percorso.exists():
        raise ErroreEstrazione(f"Il file {percorso} non esiste.")
    estensione = percorso.suffix.lower()
    if estensione == ".pdf":
        return estrai_da_pdf(percorso)
    if estensione in FORMATI_IMMAGINE:
        return estrai_da_foto(percorso)
    raise ErroreEstrazione(f"Formato {estensione} non supportato: mandami un PDF, una foto JPG/PNG o scrivimi i dati.")
