"""
LE BOZZE - la "sala d'attesa" prima del registro
=================================================

Requisito (funzione 2): un'estrazione ASSISTITA:
   - se un dato manca, l'assistente lo chiede;
   - l'utente può modificare, confermare o annullare la bozza PRIMA del salvataggio.

Quindi una fattura NON va dritta nel registro. Il percorso è:

   file/testo --estrazione--> BOZZA --(l'utente corregge / completa)--> CONFERMA --> REGISTRO
                                 |
                                 +--------------------------------> ANNULLA (non si registra)

Le bozze sono salvate in un file JSON ("bozze PERSISTENTI"): se il programma si
chiude a metà, al riavvio la bozza c'è ancora e si riprende da dove si era rimasti.

Come il registro, anche qui è tutto Python: l'LLM decide QUANDO usare queste
funzioni (tramite i tool), ma i controlli e le conversioni le fa Python.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import archivio
import avvisi
import config
import registro_fatture as reg
from fatture_comuni import euro_in_centesimi, normalizza_data

BOZZE = config.BOZZE

CAMPI_OBBLIGATORI = ["fornitore", "partita_iva", "numero", "data_emissione", "data_scadenza",
                     "imponibile_cent", "iva_cent", "totale_cent"]
CAMPI_MODIFICABILI = CAMPI_OBBLIGATORI + ["regime_iva"]
CAMPI_IMPORTO = {"imponibile_cent", "iva_cent", "totale_cent"}
CAMPI_DATA = {"data_emissione", "data_scadenza"}
REGIMI_IVA = {"ordinario", "inversione_contabile", "aliquota_ridotta", "esente"}
GIORNI_SCADENZA_PROPOSTA = 30


# ---------------------------------------------------------------------------
# FILE DELLE BOZZE
# ---------------------------------------------------------------------------

def _carica() -> list:
    if not BOZZE.exists():
        return []
    return json.loads(BOZZE.read_text(encoding="utf-8"))


def _salva(bozze: list) -> None:
    temporaneo = BOZZE.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(bozze, ensure_ascii=False, indent=2), encoding="utf-8")
    temporaneo.replace(BOZZE)


def svuota_bozze() -> None:
    """Solo per le prove."""
    _salva([])


def _trova(bozze: list, id_bozza: str) -> Optional[dict]:
    for b in bozze:
        if b["id"].lower() == id_bozza.strip().lower():
            return b
    return None


# ---------------------------------------------------------------------------
# CONTROLLI SULLA BOZZA (ricalcolati a ogni modifica)
# ---------------------------------------------------------------------------

def _aggiorna_controlli(b: dict) -> None:
    d = b["dati"]
    b["mancanti"] = [c for c in CAMPI_OBBLIGATORI if d.get(c) in (None, "")]

    avvisi = []
    imp, iva, tot = d.get("imponibile_cent"), d.get("iva_cent"), d.get("totale_cent")
    if None not in (imp, iva, tot) and imp + iva != tot:
        avvisi.append(f"Importi incoerenti: {reg.centesimi_in_euro(imp)} + {reg.centesimi_in_euro(iva)} "
                      f"non fa {reg.centesimi_in_euro(tot)}.")
    # P.IVA: il controllo lo fa Python. L'LLM, lasciato fare, ha detto che una P.IVA di 11 cifre
    # "sembrava lunga": contare le cifre non è una cosa che sa fare in modo affidabile.
    piva = d.get("partita_iva")
    if piva and not (piva.isdigit() and len(piva) == 11):
        avvisi.append(f"Partita IVA '{piva}' non valida: deve avere esattamente 11 cifre (ne ha "
                      f"{sum(c.isdigit() for c in piva)}). Verificala.")
    if d.get("regime_iva") not in (None, "ordinario"):
        avvisi.append(f"Regime IVA non ordinario ({d['regime_iva'].replace('_', ' ')}): da verificare.")
    doppione = reg.cerca_duplicato(reg.carica_registro(), d.get("partita_iva"), d.get("fornitore"), d.get("numero"))
    if doppione:
        avvisi.append(f"POSSIBILE DUPLICATO: nel registro c'è già {doppione['id']} "
                      f"({doppione['fornitore']}, n. {doppione['numero']}).")
    b["avvisi"] = avvisi

    # Scadenza mancante: Python PROPONE una data (emissione + 30 giorni), l'utente decide.
    # L'LLM non calcola date (vedi RELAZIONE, limiti osservati).
    b["proposta_scadenza"] = None
    if not d.get("data_scadenza") and d.get("data_emissione"):
        proposta = date.fromisoformat(d["data_emissione"]) + timedelta(days=GIORNI_SCADENZA_PROPOSTA)
        b["proposta_scadenza"] = proposta.isoformat()


def _descrivi(b: dict) -> str:
    """Testo che l'agente leggerà per mostrare la bozza all'utente."""
    d = b["dati"]
    euro = reg.centesimi_in_euro
    righe = [
        f"Bozza {b['id']} (stato: {b['stato']}, origine: {b['origine']})",
        f"  fornitore:      {d.get('fornitore') or '-- MANCA --'}",
        f"  partita IVA:    {d.get('partita_iva') or '-- MANCA --'}",
        f"  numero:         {d.get('numero') or '-- MANCA --'}",
        f"  data emissione: {d.get('data_emissione') or '-- MANCA --'}",
        f"  data scadenza:  {d.get('data_scadenza') or '-- MANCA --'}",
        f"  imponibile:     {euro(d.get('imponibile_cent')) if d.get('imponibile_cent') is not None else '-- MANCA --'}",
        f"  IVA:            {euro(d.get('iva_cent')) if d.get('iva_cent') is not None else '-- MANCA --'}",
        f"  totale:         {euro(d.get('totale_cent')) if d.get('totale_cent') is not None else '-- MANCA --'}",
        f"  regime IVA:     {d.get('regime_iva')}",
    ]
    if b["mancanti"]:
        righe.append(f"DATI MANCANTI da chiedere all'utente: {', '.join(b['mancanti'])}")
    if b.get("proposta_scadenza"):
        righe.append(f"PROPOSTA per la scadenza (emissione + {GIORNI_SCADENZA_PROPOSTA} giorni): "
                     f"{b['proposta_scadenza']} -- va CONFERMATA dall'utente, non è scritta sulla fattura.")
    for a in b["avvisi"]:
        righe.append(f"AVVISO: {a}")
    if not b["mancanti"] and b["stato"] == "aperta":
        righe.append("La bozza è completa: chiedi all'utente se confermare il salvataggio.")
    return "\n".join(righe)


# ---------------------------------------------------------------------------
# LE OPERAZIONI SULLE BOZZE
# ---------------------------------------------------------------------------

def crea_bozza(dati_estratti: dict, origine: str, percorso_originale: Optional[str] = None) -> str:
    bozze = _carica()
    b = {
        "id": f"B{len(bozze) + 1:04d}",
        "stato": "aperta",                  # aperta -> confermata / annullata
        "origine": origine,                 # nome del file o "testo"
        "dati": {c: dati_estratti.get(c) for c in CAMPI_MODIFICABILI},
        "creata_il": datetime.now().isoformat(timespec="seconds"),
        "id_fattura": None,                 # verrà riempito alla conferma
    }
    b["dati"]["regime_iva"] = b["dati"]["regime_iva"] or "ordinario"
    b["dati"]["file"] = dati_estratti.get("file")
    b["dati"]["percorso_originale"] = str(percorso_originale) if percorso_originale else None
    _aggiorna_controlli(b)
    bozze.append(b)
    _salva(bozze)
    return _descrivi(b)


def mostra_bozza(id_bozza: str) -> str:
    b = _trova(_carica(), id_bozza)
    return _descrivi(b) if b else f"Nessuna bozza con id {id_bozza}."


def elenca_bozze_aperte() -> str:
    aperte = [b for b in _carica() if b["stato"] == "aperta"]
    if not aperte:
        return "Nessuna bozza aperta."
    return "\n".join(f"{b['id']} | {b['dati'].get('fornitore') or '?'} | n. {b['dati'].get('numero') or '?'} | "
                     f"mancano: {', '.join(b['mancanti']) or 'niente'}" for b in aperte)


def modifica_bozza(id_bozza: str, campo: str, valore: str) -> str:
    """
    Cambia un campo. Il valore arriva come TESTO (come lo scrive l'utente):
    Python lo converte - importi in centesimi, date in AAAA-MM-GG.
    """
    bozze = _carica()
    b = _trova(bozze, id_bozza)
    if b is None:
        return f"Nessuna bozza con id {id_bozza}."
    if b["stato"] != "aperta":
        return f"La bozza {b['id']} è {b['stato']}: non si può più modificare."
    if campo not in CAMPI_MODIFICABILI:
        return f"Campo '{campo}' non valido. Campi modificabili: {', '.join(CAMPI_MODIFICABILI)}."

    if campo in CAMPI_IMPORTO:
        try:
            nuovo = euro_in_centesimi(valore)
        except Exception:
            return f"Non capisco l'importo '{valore}': scrivilo come 1.234,56"
    elif campo in CAMPI_DATA:
        nuovo = normalizza_data(valore)
        if nuovo is None:
            return f"Non capisco la data '{valore}': scrivila come GG/MM/AAAA"
    elif campo == "regime_iva":
        if valore not in REGIMI_IVA:
            return f"Regime IVA non valido. Valori ammessi: {', '.join(sorted(REGIMI_IVA))}."
        nuovo = valore
    else:
        nuovo = valore.strip()

    b["dati"][campo] = nuovo
    _aggiorna_controlli(b)
    _salva(bozze)
    return "Modifica fatta.\n" + _descrivi(b)


def conferma_bozza(id_bozza: str) -> str:
    """Salva DEFINITIVAMENTE la bozza nel registro (solo se completa e non duplicata)."""
    bozze = _carica()
    b = _trova(bozze, id_bozza)
    if b is None:
        return f"Nessuna bozza con id {id_bozza}."
    if b["stato"] != "aperta":
        return f"La bozza {b['id']} è già {b['stato']}."
    _aggiorna_controlli(b)
    if b["mancanti"]:
        return f"Non posso confermare: mancano ancora {', '.join(b['mancanti'])}."

    esito = reg.registra_fattura(b["dati"])
    if esito["esito"] != "registrata":
        return f"Non registrata. {esito['messaggio']}"
    b["stato"] = "confermata"
    b["id_fattura"] = esito["id"]
    _salva(bozze)
    # Subito dopo la registrazione, l'originale va su Google Drive.
    # Se Drive non risponde la fattura resta registrata e l'archiviazione si riprova dopo.
    esito_drive = archivio.archivia_fattura(esito["id"])
    # Avviso configurabile se la fattura supera la soglia del .env.
    sopra_soglia = avvisi.controlla_importo(reg.trova_fattura(esito["id"]))
    return (esito["messaggio"] + "".join(f"\nAVVISO: {a}" for a in esito["avvisi"])
            + f"\n{esito_drive}"
            + (f"\nAVVISO SOGLIA (inviato anche ai destinatari degli avvisi): {sopra_soglia}" if sopra_soglia else ""))


def annulla_bozza(id_bozza: str) -> str:
    """La bozza viene scartata: non entra nel registro (ma resta nel file delle bozze come 'annullata')."""
    bozze = _carica()
    b = _trova(bozze, id_bozza)
    if b is None:
        return f"Nessuna bozza con id {id_bozza}."
    if b["stato"] != "aperta":
        return f"La bozza {b['id']} è già {b['stato']}."
    b["stato"] = "annullata"
    _salva(bozze)
    return f"Bozza {b['id']} annullata: non è stata registrata."
