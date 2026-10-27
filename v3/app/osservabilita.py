"""
OSSERVABILITÀ DELLE CHIAMATE ALL'LLM (Langfuse) - FACOLTATIVA
=============================================================

Langfuse registra ogni chiamata al modello: cosa gli è stato chiesto, cosa ha risposto, quanto tempo
e quanti token. È la "scatola nera" del bot: se una risposta è sbagliata si vede esattamente perché.

Si accende solo se nel .env ci sono LANGFUSE_PUBLIC_KEY e LANGFUSE_SECRET_KEY (più LANGFUSE_BASE_URL,
es. https://cloud.langfuse.com). Senza chiavi non cambia nulla: niente rete, niente errori.

Uso con LangChain / LangGraph:   modello.invoke(messaggi, config=osservabilita.config())
"""

import os
from typing import Optional

import config as _impostazioni  # noqa: F401  (carica il .env)


def attiva() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def callbacks() -> list:
    """Il callback di Langfuse per LangChain, oppure nessuno se Langfuse non è configurato."""
    if not attiva():
        return []
    from langfuse.langchain import CallbackHandler
    return [CallbackHandler()]


def config(nome: Optional[str] = None, **altro) -> dict:
    """Il parametro config= di invoke(): i callback di Langfuse e il nome che si vede nella traccia."""
    conf = {"callbacks": callbacks(), **altro}
    if nome:
        conf["run_name"] = nome
    return conf


def client():
    """Il client Langfuse (per i punteggi delle valutazioni), oppure None."""
    if not attiva():
        return None
    from langfuse import get_client
    return get_client()
