"""
RAG SUL CONTENUTO DELLE FATTURE (v2)
====================================

Il registro conosce fornitore, numero, date e importi, ma NON cosa c'è scritto nelle fatture
(righe degli articoli, descrizioni dei servizi, note, condizioni). Il RAG permette domande come
"chi mi ha venduto il toner?" o "quali consulenze ho ricevuto?".

- Il testo completo di ogni fattura del registro si ricava dal suo ORIGINALE:
  PDF -> pypdf · foto -> trascrizione con modello vision · vocale -> trascrizione audio · .txt -> letto.
  Si calcola una sola volta e si salva in dati/v2_rag_testi.json (cache).
- Embedding text-embedding-3-small + InMemoryVectorStore; l'indice si costruisce al primo uso
  e si aggiorna quando il grafo registra una fattura nuova (aggiungi()).
- Esposto all'agente come tool: le domande su COSA è stato acquistato vanno qui,
  quelle su QUANTO / stato di pagamento vanno ai tool del registro.
"""

import base64
import json
import threading
from pathlib import Path

import percorsi_v2 as P  # noqa: F401

import registro_fatture as reg
from fatture_comuni import leggi_pdf
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from trascrizione import FORMATI_AUDIO, trascrivi

_indice = None
_lucchetto = threading.Lock()


def _testo_originale(percorso: Path) -> str:
    estensione = percorso.suffix.lower()
    if estensione == ".pdf":
        return leggi_pdf(percorso)
    if estensione in (".jpg", ".jpeg", ".png"):
        tipo = "png" if estensione == ".png" else "jpeg"
        immagine = base64.b64encode(percorso.read_bytes()).decode()
        return init_chat_model("openai:gpt-4.1-mini", temperature=0).invoke([HumanMessage(content=[
            {"type": "text", "text": "Trascrivi fedelmente tutto il testo di questa fattura, comprese le righe "
                                     "degli articoli. Solo il testo."},
            {"type": "image_url", "image_url": {"url": f"data:image/{tipo};base64,{immagine}", "detail": "high"}},
        ])]).content
    if estensione in FORMATI_AUDIO:
        return trascrivi(percorso)
    return percorso.read_text(encoding="utf-8")


def _documento(fattura: dict, cache: dict):
    if fattura["id"] not in cache:
        percorso = Path(fattura.get("percorso_originale") or "")
        if not percorso.is_absolute():                 # es. nel registro di esempio: file_di_prova/...
            percorso = P.config.BASE / percorso
        if not fattura.get("percorso_originale") or not percorso.is_file():
            return None
        cache[fattura["id"]] = _testo_originale(percorso)
    intestazione = (f"[{fattura['id']} | {fattura['fornitore']} | fattura n. {fattura['numero']} "
                    f"del {fattura['data_emissione']}]")
    return Document(page_content=f"{intestazione}\n{cache[fattura['id']]}",
                    metadata={"id": fattura["id"], "fornitore": fattura["fornitore"], "numero": fattura["numero"]})


def _cache() -> dict:
    return json.loads(P.RAG_TESTI.read_text(encoding="utf-8")) if P.RAG_TESTI.exists() else {}


def _indice_pronto() -> InMemoryVectorStore:
    global _indice
    with _lucchetto:
        if _indice is None:
            cache = _cache()
            documenti = [d for f in reg.carica_registro() if not f["annullata"] and (d := _documento(f, cache))]
            P.RAG_TESTI.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            _indice = InMemoryVectorStore(OpenAIEmbeddings(model="text-embedding-3-small"))
            if documenti:
                _indice.add_documents(documenti)
        return _indice


def aggiungi(fattura: dict) -> None:
    """Chiamata dal grafo dopo una registrazione: la fattura nuova diventa subito cercabile."""
    indice = _indice_pronto()
    cache = _cache()
    documento = _documento(fattura, cache)
    if documento:
        P.RAG_TESTI.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        with _lucchetto:
            indice.add_documents([documento])


@tool(response_format="content_and_artifact")
def cerca_nel_contenuto_delle_fatture(domanda: str):
    """Cerca nel TESTO delle fatture registrate: righe degli articoli, descrizioni dei servizi, note,
    condizioni, IBAN. Usalo per domande su COSA è stato acquistato o su cosa c'è scritto nelle fatture.
    Per totali, stato di pagamento e scadenze usa invece i tool del registro.

    Args:
        domanda: cosa cercare, in parole semplici (es. 'toner', 'consulenza strategica').
    """
    trovati = _indice_pronto().similarity_search(domanda, k=4)
    if not trovati:
        return "Nessuna fattura pertinente trovata.", []
    return "\n\n".join(d.page_content for d in trovati), trovati
