"""
Collegamento alla v1 e percorsi della v2.

La v2 NON copia il codice della v1: ne riusa i moduli (registro, estrazione, controlli, Google,
avvisi, commercialista). Questo file rende importabili i moduli di ../codice e definisce
i file in più che servono solo alla v2 (tutti dentro dati/, esclusa dal repository).
Va importato per primo da ogni file della v2.
"""

import sys
from pathlib import Path

CODICE_V1 = Path(__file__).resolve().parent.parent / "codice"
if str(CODICE_V1) not in sys.path:
    sys.path.insert(0, str(CODICE_V1))

import config  # noqa: E402  (della v1: carica il .env e crea le cartelle)

GRAFO_DB = config.DATI / "v2_grafo_bozze.sqlite"      # stato dei grafi delle bozze (anche a metà)
AGENTE_DB = config.DATI / "v2_agente.sqlite"          # memoria delle conversazioni dell'agente
BOZZE_APERTE = config.DATI / "v2_bozze_aperte.json"   # chat -> grafo in attesa di una risposta
RAG_TESTI = config.DATI / "v2_rag_testi.json"         # testo completo di ogni fattura (cache del RAG)
