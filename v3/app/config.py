"""
Configurazione centrale: percorsi e caricamento del file .env.

Tutti i percorsi partono dalla cartella del progetto, ovunque venga copiata:
nessun percorso del computer di sviluppo è scritto nel codice.

    v3/
        .env                  segreti e impostazioni (NON nel repository, vedi .env.example)
        app/                  questo codice
        tests/                test automatici (pytest)
        dati/                 registro, bozze, file ricevuti, riepiloghi (NON nel repository)
        log/                  errori.log (NON nel repository)
        segreti/              credenziali e token Google (NON nel repository)
        file_di_prova/        fatture di prova usate per l'acquisizione
        valutazione/          golden set e risultati della valutazione
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
ANAGRAFICA_ESTERI = DATI / "anagrafica_fornitori_esteri.json"
CAMBI_BDI = DATI / "cambi_bdi.json"          # cambi già scaricati dalla Banca d'Italia (per non richiederli)

# La nostra azienda: compare in ogni fattura come CLIENTE, mai come fornitore.
# Si imposta nel .env (non nel codice): lo stesso programma serve aziende diverse.
AZIENDA_NOME = os.getenv("AZIENDA_NOME") or None

# Modelli di lettura: si scelgono dalla configurazione (e si confrontano con gli esperimenti MLflow),
# non si cambiano nel codice.
MODELLO_TESTO = os.getenv("MODELLO_LETTURA_TESTO", "gpt-4.1-mini")   # scelto con MLflow: estere 7/7 contro 6/7
MODELLO_FOTO = os.getenv("MODELLO_LETTURA_FOTO", "gpt-4.1-mini")
# Interprete delle risposte dell'utente: scelto con DSPy + MLflow (con 16 esempi: 98,6% contro 88,9% del
# prompt scritto a mano con gpt-4.1-mini), e costa meno.
MODELLO_INTERPRETE = os.getenv("MODELLO_INTERPRETE", "gpt-4o-mini")
AZIENDA_PIVA = (os.getenv("AZIENDA_PIVA") or "").upper().removeprefix("IT") or None

LOG = BASE / "log"
SEGRETI = BASE / "segreti"
GOOGLE_CREDENZIALI = SEGRETI / "google_credenziali.json"
GOOGLE_TOKEN = SEGRETI / "google_token.json"

FILE_DI_PROVA = BASE / "file_di_prova"
VALUTAZIONE = BASE / "valutazione"
GOLDEN_SET = VALUTAZIONE / "golden_set.json"

for cartella in (DATI, RICEVUTI, RIEPILOGHI, LOG, SEGRETI):
    cartella.mkdir(parents=True, exist_ok=True)
