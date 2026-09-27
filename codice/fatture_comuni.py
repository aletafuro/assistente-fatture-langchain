"""
PEZZI COMUNI: schema dei dati della fattura, conversioni e controlli.

Principio del progetto: L'LLM LEGGE, PYTHON CONVERTE E CONTA.
L'LLM copia importi e date COME SONO SCRITTI ("1.200,00", "12/03/2025", "22 settembre 2026");
Python li converte in centesimi interi e in date AAAA-MM-GG e fa tutti i controlli.
"""

import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pypdf import PdfReader

import config

GOLDEN_SET = config.GOLDEN_SET

CAMPI_CONFRONTO = ["fornitore", "partita_iva", "numero", "data_emissione", "data_scadenza",
                   "imponibile_cent", "iva_cent", "totale_cent", "regime_iva"]

ISTRUZIONI_ESTRAZIONE = (
    "Sei un assistente contabile italiano. Estrai i dati dalla fattura che ti viene fornita. "
    "Attenzione: nelle fatture compare sia il fornitore (chi emette) sia il cliente (chi riceve): "
    "i campi fornitore e partita_iva riguardano SOLO il fornitore. "
    "Non inventare mai: se un dato non è presente, lascialo vuoto."
)


class DatiFattura(BaseModel):
    """Dati principali di una fattura ricevuta da un fornitore."""

    fornitore: Optional[str] = Field(
        default=None,
        description="Ragione sociale di chi EMETTE la fattura (il fornitore). NON il cliente/destinatario.")
    partita_iva: Optional[str] = Field(
        default=None,
        description="Partita IVA del FORNITORE: solo le 11 cifre, senza 'IT' e senza spazi.")
    numero: Optional[str] = Field(
        default=None,
        description="Numero della fattura, copiato esattamente come scritto (es. '2026/037').")
    data_emissione: Optional[str] = Field(
        default=None,
        description="Data di emissione copiata ESATTAMENTE come scritta, senza cambiarne il formato "
                    "(es. '12/03/2025' oppure '2026-06-10').")
    data_scadenza: Optional[str] = Field(
        default=None,
        description="Data di scadenza del pagamento copiata ESATTAMENTE come scritta. "
                    "Se non c'è una data scritta esplicitamente, lascia vuoto: non calcolarla.")
    imponibile: Optional[str] = Field(
        default=None,
        description="Imponibile copiato come scritto sulla fattura, es. '1.200,00'. Senza simbolo €.")
    iva: Optional[str] = Field(
        default=None,
        description="Importo dell'IVA copiato come scritto, es. '264,00'. Senza simbolo €.")
    totale: Optional[str] = Field(
        default=None,
        description="Totale documento copiato come scritto, es. '1.464,00'. Senza simbolo €.")
    regime_iva: Literal["ordinario", "inversione_contabile", "aliquota_ridotta", "esente"] = Field(
        description="'ordinario' se IVA al 22%; 'inversione_contabile' se reverse charge; "
                    "'aliquota_ridotta' se IVA al 4%, 5% o 10%; 'esente' se esente/non imponibile.")


logging.getLogger("pypdf").setLevel(logging.ERROR)   # niente messaggi tecnici di pypdf a video


def leggi_pdf(percorso: Path) -> str:
    lettore = PdfReader(percorso)
    return "\n".join(pagina.extract_text() for pagina in lettore.pages)


def euro_in_centesimi(testo: Optional[str]) -> Optional[int]:
    if testo is None:
        return None
    pulito = testo.replace("€", "").replace(" ", "").strip()
    if "," in pulito:                       # formato italiano: 1.200,00
        pulito = pulito.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", pulito):
        # "6.100" o "1.500.000" senza virgola: il punto separa le MIGLIAIA, non i decimali
        # (prima "6.100 euro" veniva letto come 6,10 €).
        pulito = pulito.replace(".", "")
    return int(Decimal(pulito) * 100)


def vuoto_se_niente(testo: Optional[str]) -> Optional[str]:
    """A volte l'LLM risponde '' (stringa vuota) invece di lasciare vuoto: per noi è la stessa cosa."""
    if testo is None or testo.strip() == "":
        return None
    return testo.strip()


MESI_ITALIANI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
                 "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}


def normalizza_data(testo: Optional[str]) -> Optional[str]:
    """Da '12/03/2025', '2025-03-12' o '12 marzo 2025' sempre a '2025-03-12' (formato AAAA-MM-GG)."""
    testo = vuoto_se_niente(testo)
    if testo is None:
        return None
    # Date a parole (vocali e chat): "22 settembre 2026" -> "22/09/2026"
    parole = testo.lower().replace(",", " ").split()
    if len(parole) == 3 and parole[1] in MESI_ITALIANI:
        testo = f"{parole[0]}/{MESI_ITALIANI[parole[1]]}/{parole[2]}"
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(testo, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None   # formato sconosciuto: meglio vuoto (e chiederlo) che sbagliato


def controlla_coerenza(imponibile_cent, iva_cent, totale_cent) -> bool:
    """Controllo contabile: imponibile + IVA deve fare esattamente il totale."""
    if None in (imponibile_cent, iva_cent, totale_cent):
        return False
    return imponibile_cent + iva_cent == totale_cent


def in_dizionario(nome_file: str, dati: DatiFattura) -> dict:
    """Trasforma quello che ha letto l'LLM in un dizionario con gli importi in centesimi."""
    return {
        "file": nome_file,
        "fornitore": vuoto_se_niente(dati.fornitore),
        "partita_iva": vuoto_se_niente(dati.partita_iva),
        "numero": vuoto_se_niente(dati.numero),
        "data_emissione": normalizza_data(dati.data_emissione),
        "data_scadenza": normalizza_data(dati.data_scadenza),
        "imponibile_cent": euro_in_centesimi(vuoto_se_niente(dati.imponibile)),
        "iva_cent": euro_in_centesimi(vuoto_se_niente(dati.iva)),
        "totale_cent": euro_in_centesimi(vuoto_se_niente(dati.totale)),
        "regime_iva": dati.regime_iva,
    }


def carica_golden_set() -> dict:
    return {riga["file"]: riga for riga in json.load(open(GOLDEN_SET, encoding="utf-8"))}


def _per_confronto(campo: str, valore) -> str:
    testo = str(valore).strip().lower()
    if campo == "fornitore":
        # "Cartoleria Bianchi S.r.l." e "Cartoleria Bianchi SRL" sono lo stesso fornitore:
        # la punteggiatura della forma societaria non conta, le lettere sì ("Cartoneria" resta un errore).
        testo = "".join(c for c in testo if c.isalnum())
    return testo


def campi_sbagliati(estratto: dict, atteso: dict) -> list:
    return [c for c in CAMPI_CONFRONTO
            if _per_confronto(c, estratto[c]) != _per_confronto(c, atteso[c])]
