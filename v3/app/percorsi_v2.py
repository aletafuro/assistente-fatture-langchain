"""
Percorsi dei file del grafo, dell'agente e del RAG (tutti dentro dati/, esclusa dal repository).

Nella v2 questo file agganciava anche i moduli della v1 (cartella ../codice). Nella v3 tutto il codice
sta in una sola cartella (app/), quindi resta solo l'elenco dei percorsi.
"""

import config  # carica il .env e crea le cartelle

GRAFO_DB = config.DATI / "v2_grafo_bozze.sqlite"      # stato dei grafi delle bozze (anche a metà)
AGENTE_DB = config.DATI / "v2_agente.sqlite"          # memoria delle conversazioni dell'agente
BOZZE_APERTE = config.DATI / "v2_bozze_aperte.json"   # chat -> grafo in attesa di una risposta
RAG_TESTI = config.DATI / "v2_rag_testi.json"         # testo completo di ogni fattura (cache del RAG)
