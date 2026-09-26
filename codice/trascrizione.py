"""
TRASCRIZIONE DEI MESSAGGI VOCALI
================================

L'LLM dell'estrazione legge TESTO e IMMAGINI, ma non ascolta l'audio.
Per i vocali serve un passo in più, fatto da un modello specializzato:

   vocale (.ogg) --modello di trascrizione--> testo --estrazione (come in chat)--> bozza

Usiamo il modello di trascrizione di OpenAI (stessa chiave OPENAI_API_KEY).
Qui non passiamo da LangChain: chiamiamo direttamente la libreria openai,
perché LangChain non serve per un'operazione così semplice (input audio -> testo).

Telegram salva i vocali in formato .ogg: OpenAI lo accetta così com'è.
"""

from pathlib import Path


from openai import OpenAI

import avvisi

MODELLO_TRASCRIZIONE = "gpt-4o-mini-transcribe"
FORMATI_AUDIO = {".ogg", ".oga", ".mp3", ".m4a", ".wav", ".webm", ".mp4", ".mpeg", ".mpga"}

_client = OpenAI()   # legge da solo OPENAI_API_KEY


class ErroreTrascrizione(Exception):
    """Errore 'gentile': il messaggio si può mostrare così com'è all'utente."""


def trascrivi(percorso: Path) -> str:
    percorso = Path(percorso)
    if percorso.suffix.lower() not in FORMATI_AUDIO:
        raise ErroreTrascrizione(f"Formato audio {percorso.suffix} non supportato.")
    try:
        with open(percorso, "rb") as audio:
            risultato = _client.audio.transcriptions.create(
                model=MODELLO_TRASCRIZIONE,
                file=audio,
                language="it",   # dire la lingua aiuta con numeri e nomi italiani
                # Il prompt "prepara" il modello al tipo di parole che sentirà.
                prompt="Dettatura dei dati di una fattura: fornitore, partita IVA, numero, date, "
                       "imponibile, IVA, totale in euro.",
            )
    except Exception as errore:
        avvisi.errore_tecnico("OpenAI (trascrizione vocali)", errore)
        raise ErroreTrascrizione(f"Il servizio di trascrizione non è disponibile ({type(errore).__name__}). "
                                 "Riprova tra poco oppure scrivimi i dati.")
    testo = risultato.text.strip()
    if not testo:
        raise ErroreTrascrizione("Non ho sentito nessuna parola nel vocale: puoi ripeterlo?")
    return testo
