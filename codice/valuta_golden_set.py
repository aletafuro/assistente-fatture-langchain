"""
VALUTAZIONE DELL'ESTRAZIONE SUL GOLDEN SET
==========================================

Per ogni fattura del golden set (valutazione/golden_set.json, dati attesi verificati a mano)
esegue la STESSA estrazione usata dal bot, per il suo canale:
    PDF  -> pypdf + LLM            foto  -> LLM vision
    vocale -> trascrizione + LLM   testo -> LLM
e confronta campo per campo. Ripete tutto N volte (default 3), perché un singolo giro
giusto non dimostra che l'estrazione sia stabile.

Uso (dalla cartella del progetto):   python codice/valuta_golden_set.py [numero_giri]

Scrive:
    valutazione/risultati_valutazione.json   (tutti i valori estratti)
    valutazione/VALUTAZIONE.md               (tabella leggibile, da allegare alla relazione)
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from estrazione import ErroreEstrazione, estrai_da_file, estrai_da_testo
from fatture_comuni import CAMPI_CONFRONTO, campi_sbagliati, carica_golden_set
from trascrizione import trascrivi

CANALI = {"pdf": "PDF", "foto": "Foto", "vocale": "Vocale", "testo": "Testo"}


def trova_file(nome: str) -> tuple:
    for cartella in CANALI:
        percorso = config.FILE_DI_PROVA / cartella / nome
        if percorso.exists():
            return cartella, percorso
    raise FileNotFoundError(nome)


def estrai(canale: str, percorso: Path) -> dict:
    if canale == "vocale":
        return estrai_da_testo(trascrivi(percorso), percorso.name)
    if canale == "testo":
        return estrai_da_testo(percorso.read_text(encoding="utf-8"), percorso.name)
    return estrai_da_file(percorso)


def main(giri: int) -> None:
    golden = carica_golden_set()
    risultati = []
    inizio = time.time()
    for giro in range(1, giri + 1):
        for nome, atteso in golden.items():
            canale, percorso = trova_file(nome)
            try:
                estratto = estrai(canale, percorso)
                sbagliati = campi_sbagliati(estratto, atteso)
            except ErroreEstrazione as errore:
                estratto, sbagliati = {"errore": str(errore)}, list(CAMPI_CONFRONTO)
            risultati.append({"giro": giro, "file": nome, "canale": canale,
                              "corretta": not sbagliati, "campi_sbagliati": sbagliati,
                              "estratto": estratto})
            segno = "OK " if not sbagliati else "ERR"
            print(f"giro {giro} {segno} {canale:6} {nome}" + (f"  -> {sbagliati}" if sbagliati else ""))

    durata = time.time() - inizio
    (config.VALUTAZIONE / "risultati_valutazione.json").write_text(
        json.dumps(risultati, ensure_ascii=False, indent=2), encoding="utf-8")
    scrivi_rapporto(golden, risultati, giri, durata)


def scrivi_rapporto(golden: dict, risultati: list, giri: int, durata: float) -> None:
    righe = [
        "# Valutazione dell'estrazione — golden set",
        "",
        f"Eseguita il {datetime.now():%d/%m/%Y %H:%M} · {len(golden)} fatture · {giri} giri · "
        f"{len(risultati)} estrazioni · durata {durata / 60:.1f} minuti.",
        "Una fattura è **corretta** solo se **tutti i 9 campi** coincidono con i dati attesi "
        "(fornitore, partita IVA, numero, data emissione, data scadenza, imponibile, IVA, totale, regime IVA).",
        "",
        "## Risultato per canale",
        "",
        "| Canale | Fatture | Estrazioni | Corrette | Percentuale |",
        "|---|---|---|---|---|",
    ]
    for canale, etichetta in CANALI.items():
        del_canale = [r for r in risultati if r["canale"] == canale]
        if not del_canale:
            continue
        corrette = sum(r["corretta"] for r in del_canale)
        righe.append(f"| {etichetta} | {len(del_canale) // giri} | {len(del_canale)} | {corrette} | "
                     f"{100 * corrette / len(del_canale):.0f}% |")
    corrette = sum(r["corretta"] for r in risultati)
    righe.append(f"| **Totale** | **{len(golden)}** | **{len(risultati)}** | **{corrette}** | "
                 f"**{100 * corrette / len(risultati):.0f}%** |")

    righe += ["", "## Dettaglio per fattura", "",
              "| File | Canale | " + " | ".join(f"Giro {g}" for g in range(1, giri + 1)) + " |",
              "|---|---|" + "---|" * giri]
    for nome in golden:
        del_file = [r for r in risultati if r["file"] == nome]
        celle = ["✅" if r["corretta"] else "❌ " + ", ".join(r["campi_sbagliati"]) for r in del_file]
        righe.append(f"| {nome} | {CANALI[del_file[0]['canale']]} | " + " | ".join(celle) + " |")

    errori_per_campo = {}
    for r in risultati:
        for campo in r["campi_sbagliati"]:
            errori_per_campo[campo] = errori_per_campo.get(campo, 0) + 1
    righe += ["", "## Errori per campo", ""]
    if errori_per_campo:
        righe += ["| Campo | Errori |", "|---|---|"] + [f"| {c} | {n} |" for c, n in sorted(errori_per_campo.items())]
    else:
        righe.append("Nessun errore su nessun campo.")

    righe += ["", "## Modelli usati", "",
              "- PDF e testo: `gpt-4o-mini` (temperature 0) con output strutturato Pydantic",
              "- Foto: `gpt-4.1-mini` (temperature 0), immagine in base64 con `detail: high`",
              "- Vocale: trascrizione `gpt-4o-mini-transcribe` (lingua it), poi estrazione come il testo",
              "- Conversioni (centesimi, date) e controlli: Python", ""]
    (config.VALUTAZIONE / "VALUTAZIONE.md").write_text("\n".join(righe), encoding="utf-8")
    print(f"\nCorrette: {corrette}/{len(risultati)} -> valutazione/VALUTAZIONE.md")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
