"""
IL REGISTRO DELLE FATTURE - solo Python, niente LLM
====================================================

Qui c'è la "contabilità" del progetto: salvare, cercare, pagare, annullare, riassumere.
È tutto Python normale, SENZA intelligenza artificiale. Perché?
Perché queste operazioni devono essere SEMPRE esatte e ripetibili:
un totale o un controllo duplicati non può "variare" come la risposta di un LLM.
(Regola del progetto: l'LLM legge, Python converte e conta.)

Il registro è un file JSON: una lista di fatture, ognuna è un dizionario.
In strumenti_fatture.py queste funzioni diventano TOOL che l'agente può usare.

Funzioni coperte qui:
  3. Registrazione        -> registra_fattura
  4. Controlli contabili  -> duplicati, coerenza importi, IVA non ordinaria
  5. Ciclo di vita        -> segna_pagata, annulla_fattura (annullamento LOGICO)
  6. Riepiloghi           -> riepilogo (mese / trimestre / anno)
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import config
from fatture_comuni import PIVA_ESTERO_ASSENTE

# Il file del registro (percorso definito in config.py, cartella dati/).
REGISTRO = config.REGISTRO


# ---------------------------------------------------------------------------
# LEGGERE E SCRIVERE IL FILE
# ---------------------------------------------------------------------------

class ErroreRegistro(Exception):
    """Il file del registro è illeggibile: NON lo sovrascriviamo, serve un intervento umano."""


def carica_registro() -> list:
    if not REGISTRO.exists():
        return []
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except json.JSONDecodeError as errore:
        # Caso grave (es. file modificato a mano e rovinato). Avvisiamo SUBITO, senza soglie,
        # e ci fermiamo: continuare significherebbe rischiare di sovrascrivere i dati.
        import avvisi
        avvisi.notifica("Registro fatture danneggiato",
                        f"Il file {REGISTRO.name} non è leggibile (riga {errore.lineno}). "
                        f"L'ultima copia buona è in {REGISTRO.with_suffix('.bak').name}.")
        raise ErroreRegistro(f"Il registro delle fatture è danneggiato: l'ultima copia buona è "
                             f"{REGISTRO.with_suffix('.bak').name}. Nessun dato è stato modificato.")


def salva_registro(fatture: list) -> None:
    # 1) Copia di sicurezza della versione precedente (registro.bak).
    # 2) Scriviamo su un file temporaneo e poi lo rinominiamo:
    #    se il programma si blocca a metà, il registro vecchio resta integro.
    if REGISTRO.exists():
        REGISTRO.with_suffix(".bak").write_bytes(REGISTRO.read_bytes())
    temporaneo = REGISTRO.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(fatture, ensure_ascii=False, indent=2), encoding="utf-8")
    temporaneo.replace(REGISTRO)


def svuota_registro() -> None:
    """Solo per le prove: ricomincia da un registro vuoto."""
    salva_registro([])


# ---------------------------------------------------------------------------
# PICCOLI AIUTI
# ---------------------------------------------------------------------------

def data_it(iso: Optional[str]) -> str:
    """'2026-09-30' -> '30/09/2026' (solo per mostrare: nel registro le date restano AAAA-MM-GG)."""
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) >= 10 else (iso or "?")


def centesimi_in_euro(centesimi: Optional[int]) -> str:
    """146400 -> '1.464,00 €'  (solo per mostrare i numeri: i conti restano in centesimi)."""
    if centesimi is None:
        return "?"
    euro, cent = divmod(abs(centesimi), 100)
    segno = "-" if centesimi < 0 else ""
    return f"{segno}{euro:,}".replace(",", ".") + f",{cent:02d} €"


def _pulisci(testo: Optional[str]) -> str:
    """Per confrontare numeri e partite IVA: niente spazi, tutto minuscolo."""
    return (testo or "").replace(" ", "").lower()


def _nuovo_id(fatture: list) -> str:
    return f"F{len(fatture) + 1:04d}"          # F0001, F0002, ...


def _trova(fatture: list, id_fattura: str) -> Optional[dict]:
    for f in fatture:
        if f["id"].lower() == id_fattura.strip().lower():
            return f
    return None


def _in_breve(f: dict) -> str:
    stato = "ANNULLATA" if f["annullata"] else f["stato_pagamento"].replace("_", " ")
    return (f"{f['id']} | {f['fornitore']} | n. {f['numero']} | emessa {data_it(f['data_emissione'])} | "
            f"scade {data_it(f['data_scadenza'])} | totale {centesimi_in_euro(f['totale_cent'])} | {stato}")


# ---------------------------------------------------------------------------
# 3 + 4. REGISTRARE UNA FATTURA (con i controlli)
# ---------------------------------------------------------------------------

def cerca_duplicato(fatture: list, partita_iva: Optional[str], fornitore: Optional[str], numero: Optional[str]) -> Optional[dict]:
    """
    Stessa fattura = stesso fornitore + stesso numero.
    Il fornitore lo riconosciamo dalla P.IVA (più affidabile del nome, che può
    essere scritto in modi diversi: 'Alfa Forniture SRL' / 'ALFA FORNITURE S.R.L.').
    Le fatture annullate contano lo stesso: se riarriva, va segnalata.
    """
    for f in fatture:
        stesso_numero = _pulisci(f["numero"]) == _pulisci(numero)
        # OO99999999999 è lo stesso per TUTTI i fornitori esteri senza partita IVA: lì conta il nome.
        if partita_iva and f["partita_iva"] and PIVA_ESTERO_ASSENTE not in (partita_iva, f["partita_iva"]):
            stesso_fornitore = _pulisci(f["partita_iva"]) == _pulisci(partita_iva)
        else:
            stesso_fornitore = _pulisci(f["fornitore"]) == _pulisci(fornitore)
        if stesso_numero and stesso_fornitore:
            return f
    return None


def registra_fattura(dati: dict) -> dict:
    """
    Salva una fattura nel registro, dopo i controlli.
    Restituisce un dizionario con 'esito' ('registrata' / 'duplicato' / 'errore'),
    un 'messaggio' leggibile e gli eventuali 'avvisi'.
    """
    fatture = carica_registro()

    # Controllo 1: i dati minimi ci devono essere (gli altri li chiederà l'assistente).
    obbligatori = ["fornitore", "numero", "data_emissione", "totale_cent"]
    mancanti = [c for c in obbligatori if dati.get(c) in (None, "")]
    if mancanti:
        return {"esito": "errore", "messaggio": f"Mancano dati obbligatori: {', '.join(mancanti)}", "avvisi": []}

    # Controllo 2: duplicati.
    doppione = cerca_duplicato(fatture, dati.get("partita_iva"), dati.get("fornitore"), dati.get("numero"))
    if doppione:
        return {"esito": "duplicato",
                "messaggio": f"Fattura già presente nel registro: {_in_breve(doppione)}",
                "avvisi": []}

    # Controllo 3: coerenza importi e regime IVA -> non bloccano, ma vanno segnalati.
    # Gli importi del registro sono SEMPRE in euro (convertiti al cambio BdI del giorno della fattura);
    # quelli originali in valuta restano nei campi *_valuta_cent.
    avvisi = []
    valuta = dati.get("valuta") or "EUR"
    originali = {c: dati.get(f"{c}_cent") for c in ("imponibile", "iva", "totale")}
    if valuta != "EUR":
        if dati.get("totale_eur_cent") is None:
            return {"esito": "errore", "messaggio": f"Manca il cambio {valuta}/EUR: impossibile convertire in euro.",
                    "avvisi": []}
        dati = dati | {f"{c}_cent": dati.get(f"{c}_eur_cent") for c in ("imponibile", "iva", "totale")}
    imp, iva, tot = dati.get("imponibile_cent"), dati.get("iva_cent"), dati.get("totale_cent")
    if None in (imp, iva, tot):
        avvisi.append("Importi incompleti: impossibile verificare imponibile + IVA = totale.")
    elif imp + iva != tot:
        avvisi.append(f"Importi incoerenti: {centesimi_in_euro(imp)} + {centesimi_in_euro(iva)} "
                      f"non fa {centesimi_in_euro(tot)}.")
    regime = dati.get("regime_iva") or "ordinario"
    if regime != "ordinario" and config.AVVISO_REGIME_IVA:
        avvisi.append(f"Regime IVA non ordinario ({regime.replace('_', ' ')}): da verificare con il commercialista.")

    nuova = {
        "id": _nuovo_id(fatture),
        "file": dati.get("file"),
        "fornitore": dati["fornitore"],
        "partita_iva": dati.get("partita_iva"),
        "numero": dati["numero"],
        "data_emissione": dati["data_emissione"],
        "data_scadenza": dati.get("data_scadenza"),
        "imponibile_cent": imp,
        "iva_cent": iva,
        "totale_cent": tot,
        "regime_iva": regime,
        # Fornitori esteri e valuta
        "paese_fornitore": dati.get("paese_fornitore") or "IT",
        "indirizzo_fornitore": dati.get("indirizzo_fornitore"),
        "valuta": valuta,
        "imponibile_valuta_cent": originali["imponibile"],
        "iva_valuta_cent": originali["iva"],
        "totale_valuta_cent": originali["totale"],
        "cambio_bdi": dati.get("cambio_bdi") or (dati.get("cambio_manuale") if valuta != "EUR" else None),
        "data_cambio": dati.get("data_cambio"),
        "scadenza_assente": bool(dati.get("scadenza_assente")),
        "avvisi": avvisi,
        # Ciclo di vita: ogni fattura nasce "da pagare" e non annullata.
        "stato_pagamento": "da_pagare",
        "data_pagamento": None,
        "annullata": False,
        "motivo_annullamento": None,
        "registrata_il": datetime.now().isoformat(timespec="seconds"),
        # Archiviazione su Google Drive: la compila archivio.py dopo la registrazione.
        "percorso_originale": dati.get("percorso_originale"),
        "archiviazione": None,       # None / fatto / in_attesa / nessun_originale
        "drive_link": None,
    }
    fatture.append(nuova)
    salva_registro(fatture)
    return {"esito": "registrata", "id": nuova["id"], "messaggio": f"Registrata: {_in_breve(nuova)}", "avvisi": avvisi}


def aggiorna_campi(id_fattura: str, campi: dict) -> None:
    """Aggiorna campi 'tecnici' di una fattura (es. link Drive). Usato dall'archiviazione."""
    fatture = carica_registro()
    f = _trova(fatture, id_fattura)
    if f is not None:
        f.update(campi)
        salva_registro(fatture)


def trova_fattura(id_fattura: str) -> Optional[dict]:
    return _trova(carica_registro(), id_fattura)


# ---------------------------------------------------------------------------
# 5. CICLO DI VITA: pagata / annullata
# ---------------------------------------------------------------------------

def segna_pagata(id_fattura: str, data_pagamento: Optional[str] = None) -> str:
    fatture = carica_registro()
    f = _trova(fatture, id_fattura)
    if f is None:
        return f"Nessuna fattura con id {id_fattura}."
    if f["annullata"]:
        return f"La fattura {f['id']} è annullata: non si può segnare come pagata."
    f["stato_pagamento"] = "pagata"
    f["data_pagamento"] = data_pagamento or date.today().isoformat()
    salva_registro(fatture)
    return f"Segnata come pagata il {f['data_pagamento']}: {_in_breve(f)}"


def annulla_fattura(id_fattura: str, motivo: str) -> str:
    """
    ANNULLAMENTO LOGICO: la fattura NON viene cancellata dal file.
    Mettiamo annullata=True: esce dai totali, ma resta nello storico (con il motivo).
    Così si può sempre ricostruire cosa è successo, come in una vera contabilità.
    """
    fatture = carica_registro()
    f = _trova(fatture, id_fattura)
    if f is None:
        return f"Nessuna fattura con id {id_fattura}."
    if f["annullata"]:
        return f"La fattura {f['id']} era già annullata."
    f["annullata"] = True
    f["motivo_annullamento"] = motivo
    salva_registro(fatture)
    return f"Annullata (resta nello storico): {_in_breve(f)} | motivo: {motivo}"


# ---------------------------------------------------------------------------
# CERCARE
# ---------------------------------------------------------------------------

def cerca_fatture(testo: str = "", stato: str = "tutte") -> str:
    """
    testo: filtra per fornitore o numero (vuoto = tutte).
    stato: 'tutte', 'da_pagare', 'pagata', 'annullata'.
    """
    # Ogni parola deve comparire nel fornitore, nel numero o nel codice (F0014), senza badare alla
    # punteggiatura: prima "rossi 2026/045" non trovava "Rossi S.p.A." (emerso nella prova con un'utente).
    parole = [re.sub(r"[^0-9a-z]", "", p) for p in (testo or "").lower().split()]
    parole = [p for p in parole if p]
    risultati = []
    for f in carica_registro():
        dove = re.sub(r"[^0-9a-z]", "", f"{f['fornitore']} {f['numero']} {f['id']} {f.get('partita_iva') or ''}".lower())
        if any(p not in dove for p in parole):
            continue
        if stato == "annullata" and not f["annullata"]:
            continue
        if stato in ("da_pagare", "pagata") and (f["annullata"] or f["stato_pagamento"] != stato):
            continue
        risultati.append(_in_breve(f))
    return "\n".join(risultati) if risultati else "Nessuna fattura trovata."


def fatture_in_scadenza(entro_giorni: int = 30, data_riferimento: Optional[str] = None) -> str:
    """Fatture da pagare, non annullate, che scadono entro N giorni (o già scadute)."""
    oggi = date.fromisoformat(data_riferimento) if data_riferimento else date.today()
    righe = []
    for f in carica_registro():
        if f["annullata"] or f["stato_pagamento"] == "pagata" or not f["data_scadenza"]:
            continue
        giorni = (date.fromisoformat(f["data_scadenza"]) - oggi).days
        if giorni <= entro_giorni:
            quando = f"SCADUTA da {-giorni} giorni" if giorni < 0 else f"scade tra {giorni} giorni"
            righe.append(f"{_in_breve(f)} -> {quando}")
    senza_data = [f["id"] for f in carica_registro()
                  if not f["annullata"] and f["stato_pagamento"] != "pagata" and not f["data_scadenza"]]
    testo = "\n".join(righe) if righe else f"Nessuna fattura in scadenza entro {entro_giorni} giorni."
    if senza_data:
        testo += f"\nAttenzione: fatture senza data di scadenza: {', '.join(senza_data)}"
    return f"(data di riferimento: {oggi.isoformat()})\n" + testo


# ---------------------------------------------------------------------------
# 6. RIEPILOGHI: mese / trimestre / anno
# ---------------------------------------------------------------------------

def fatture_del_periodo(tipo: str, anno: int, numero: Optional[int] = None) -> list:
    """
    tipo='mese'      numero=1..12   (es. mese 9 = settembre)
    tipo='trimestre' numero=1..4    (es. trimestre 3 = luglio-settembre)
    tipo='anno'      numero non serve
    Il periodo si calcola sulla DATA DI EMISSIONE. Le annullate sono escluse.
    """
    scelte = []
    for f in carica_registro():
        if f["annullata"]:
            continue
        d = date.fromisoformat(f["data_emissione"])
        if d.year != anno:
            continue
        if tipo == "mese" and d.month != numero:
            continue
        if tipo == "trimestre" and (d.month - 1) // 3 + 1 != numero:
            continue
        scelte.append(f)
    return scelte


def riepilogo(tipo: str, anno: int, numero: Optional[int] = None) -> str:
    if tipo not in ("mese", "trimestre", "anno"):
        return "Tipo di periodo non valido: usa 'mese', 'trimestre' o 'anno'."
    fatture = fatture_del_periodo(tipo, anno, numero)
    nome = {"mese": f"mese {numero}/{anno}", "trimestre": f"trimestre {numero} del {anno}", "anno": f"anno {anno}"}[tipo]
    if not fatture:
        return f"Riepilogo {nome}: nessuna fattura attiva."

    # I totali si sommano in CENTESIMI INTERI: esatti al centesimo, sempre.
    imponibile = sum(f["imponibile_cent"] or 0 for f in fatture)
    iva = sum(f["iva_cent"] or 0 for f in fatture)
    totale = sum(f["totale_cent"] or 0 for f in fatture)
    da_pagare = sum(f["totale_cent"] or 0 for f in fatture if f["stato_pagamento"] == "da_pagare")
    non_ordinarie = [f["id"] for f in fatture if f["regime_iva"] != "ordinario"]

    per_fornitore = {}
    for f in fatture:
        per_fornitore[f["fornitore"]] = per_fornitore.get(f["fornitore"], 0) + (f["totale_cent"] or 0)

    righe = [
        f"Riepilogo {nome}: {len(fatture)} fatture attive",
        f"  Imponibile: {centesimi_in_euro(imponibile)}",
        f"  IVA:        {centesimi_in_euro(iva)}",
        f"  Totale:     {centesimi_in_euro(totale)}",
        f"  Ancora da pagare: {centesimi_in_euro(da_pagare)}",
        "  Per fornitore:",
    ]
    for nome_fornitore, tot in sorted(per_fornitore.items(), key=lambda x: -x[1]):
        righe.append(f"    - {nome_fornitore}: {centesimi_in_euro(tot)}")
    if non_ordinarie:
        righe.append(f"  IVA non ordinaria da verificare: {', '.join(non_ordinarie)}")
    return "\n".join(righe)
