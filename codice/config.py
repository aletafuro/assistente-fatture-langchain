"""
Configurazione centrale: percorsi e caricamento del file .env.

Tutti i percorsi partono dalla cartella del progetto, ovunque venga copiata:
nessun percorso del computer di sviluppo è scritto nel codice.

    assistente-fatture/
        .env                  segreti e impostazioni (NON nel repository, vedi .env.example)
        codice/               questo codice
        dati/                 registro, bozze, file ricevuti, riepiloghi (NON nel repository)
        log/                  errori.log (NON nel repository)
        segreti/              credenziali e token Google (NON nel repository)
        file_di_prova/        fatture di prova usate per l'acquisizione
        valutazione/          golden set e risultati della valutazione
        esempio/              registro di esempio popolato
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent

load_dotenv(BASE / ".env")

# La cartella dei dati si può spostare dal .env (es. su un disco di backup).
DATI = Path(os.getenv("CARTELLA_DATI", BASE / "dati"))
REGISTRO = DATI / "registro.json"
BOZZE = DATI / "bozze.json"
RICEVUTI = DATI / "ricevuti"
RIEPILOGHI = DATI / "riepiloghi"

LOG = BASE / "log"
SEGRETI = BASE / "segreti"
GOOGLE_CREDENZIALI = SEGRETI / "google_credenziali.json"
GOOGLE_TOKEN = SEGRETI / "google_token.json"

FILE_DI_PROVA = BASE / "file_di_prova"
VALUTAZIONE = BASE / "valutazione"
GOLDEN_SET = VALUTAZIONE / "golden_set.json"

for cartella in (DATI, RICEVUTI, RIEPILOGHI, LOG, SEGRETI):
    cartella.mkdir(parents=True, exist_ok=True)
