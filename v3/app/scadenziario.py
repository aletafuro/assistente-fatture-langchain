"""
SCADENZIARIO ANNUALE DELLE FATTURE DA PAGARE
============================================

Regole dell'amministrazione (call del 26/10):
  - lo scadenziario si alimenta SOLO con le fatture mandate per lo scadenziario, giorno per giorno
    (italiane ed estere). Il blocco mensile della registrazione contabile NON lo tocca;
  - un file per anno ("Scadenziario fatture 2027.xlsx", nella cartella condivisa), che cresce a ogni fattura;
  - quando una fattura viene pagata, l'amministrazione lo dice al bot e la riga diventa "saldata".

Il file è anche suo: può aggiungere righe, note o colonne a mano. Il bot legge le colonne per NOME
(non per posizione) e aggiunge righe in fondo, senza riscrivere quello che c'è.

Una fattura con le rate ha una riga per rata (es. fattura "chat" di un fornitore: 60% a 7 gg DF, 40% a 30 gg FM).
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import config
import termini

COLONNE = ["Fornitore", "Numero Fattura", "Data Fattura", "Importo Valuta Originaria", "Valuta", "Importo EURO",
           "Termini di Pagamento", "Data di Scadenza", "Rata", "Stato", "Note"]
SALDATA = "saldata"


def file_anno(anno: int) -> Path:
    return config.CARTELLA_SCADENZIARIO / f"Scadenziario fatture {anno}.xlsx"


def _apri(anno: int):
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font
    percorso = file_anno(anno)
    if percorso.exists():
        libro = load_workbook(percorso)
        return libro, libro.worksheets[0]
    libro = Workbook()
    ws = libro.active
    ws.title = "Scadenziario fatture"
    ws.append(COLONNE)
    for c in ws[1]:
        c.font = Font(bold=True)
    for colonna, larghezza in zip("ABCDEFGHIJK", (32, 18, 13, 14, 8, 13, 16, 14, 26, 18, 45)):
        ws.column_dimensions[colonna].width = larghezza
    return libro, ws


def _indici(ws) -> dict:
    """{nome colonna: posizione}; le colonne del bot che mancano (file fatto a mano) si aggiungono in fondo."""
    intestazione = [str(c.value).strip() if c.value else "" for c in ws[1]]
    for nome in COLONNE:
        if nome not in intestazione:
            intestazione.append(nome)
            ws.cell(row=1, column=len(intestazione), value=nome)
    return {nome: intestazione.index(nome) for nome in COLONNE}


def _numero(n) -> str:
    return re.sub(r"[^0-9a-z]", "", str(n or "").lower()).lstrip("0")


def _stessa(fornitore_a, numero_a, fornitore_b, numero_b) -> bool:
    import estratti_conto
    return bool(_numero(numero_a)) and _numero(numero_a) == _numero(numero_b) and \
        estratti_conto.stesso_fornitore(str(fornitore_a or ""), str(fornitore_b or ""), alias={})


def righe(anno: int) -> list:
    """Le righe del file come dizionari {colonna: valore} (con 'riga' = numero di riga nel foglio)."""
    if not file_anno(anno).exists():
        return []
    _, ws = _apri(anno)
    pos = _indici(ws)
    elenco = []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(r):
            continue
        r = list(r) + [None] * (max(pos.values()) + 1 - len(r))
        elenco.append({nome: r[p] for nome, p in pos.items()} | {"riga": i})
    return elenco


def contiene(fornitore: str, numero: str, anni: Optional[list] = None) -> bool:
    """La fattura è già nello scadenziario? Si guarda l'anno della fattura e quello dopo (fatture di dicembre)."""
    anni = anni or [date.today().year - 1, date.today().year]
    return any(_stessa(r["Fornitore"], r["Numero Fattura"], fornitore, numero) for anno in anni for r in righe(anno))


def _data(iso: Optional[str]):
    return date.fromisoformat(iso) if iso else None


def aggiungi(voce: dict) -> str:
    """
    voce: fornitore, numero, data_emissione, importo_valuta, valuta, importo_eur, termine, scadenza, note,
    e (se ci sono) rate = [{scadenza, importo_cent, descrizione}].
    Se la fattura c'è già non la aggiunge una seconda volta.
    """
    anno = int((voce.get("data_emissione") or date.today().isoformat())[:4])
    if contiene(voce.get("fornitore"), voce.get("numero"), [anno, anno + 1]):
        return f"{voce.get('fornitore')} n. {voce.get('numero')} è già nello scadenziario: non l'ho aggiunta di nuovo."
    libro, ws = _apri(anno)
    pos = _indici(ws)
    estera = voce.get("valuta") not in (None, "EUR")

    def nuova(scadenza, importo_eur, importo_valuta, rata):
        valori = {"Fornitore": voce.get("fornitore"), "Numero Fattura": voce.get("numero"),
                  "Data Fattura": _data(voce.get("data_emissione")),
                  "Importo Valuta Originaria": float(importo_valuta) if estera and importo_valuta is not None else None,
                  "Valuta": voce.get("valuta"), "Importo EURO": float(importo_eur) if importo_eur is not None else None,
                  "Termini di Pagamento": voce.get("termine"), "Data di Scadenza": _data(scadenza), "Rata": rata,
                  "Stato": "da pagare", "Note": "; ".join(voce.get("note") or []) or None}
        riga = [None] * (max(pos.values()) + 1)
        for nome, valore in valori.items():
            riga[pos[nome]] = valore
        ws.append(riga)
        for c in ws[ws.max_row]:
            if isinstance(c.value, date):
                c.number_format = "DD/MM/YYYY"
            elif isinstance(c.value, float):
                c.number_format = "#,##0.00"

    rate = voce.get("rate")
    if rate:
        totale = voce.get("importo_valuta")
        for r in rate:
            quota = Decimal(r["importo_cent"]) / 100
            eur = (quota * voce["importo_eur"] / totale).quantize(Decimal("0.01")) \
                if voce.get("importo_eur") is not None and totale else None
            nuova(r["scadenza"], eur if estera else quota, quota, r["descrizione"])
    else:
        nuova(voce.get("scadenza"), voce.get("importo_eur"), voce.get("importo_valuta"), None)
    try:
        libro.save(file_anno(anno))
    except PermissionError:
        return f"Il file {file_anno(anno).name} è aperto: chiudilo e rimandami la fattura."
    quando = ", ".join(f"{_data(r['scadenza']):%d/%m/%Y}" for r in rate) if rate else \
        (f"{_data(voce['scadenza']):%d/%m/%Y}" if voce.get("scadenza") else "scadenza da definire")
    return f"Aggiunta allo scadenziario {anno}: {voce.get('fornitore')} n. {voce.get('numero')}, scadenza {quando}."


def segna_saldata(fornitore: str, numero: Optional[str] = None, giorno: Optional[str] = None) -> str:
    """'Saldata' sulle righe da pagare di quella fattura (tutte le rate, se non si dice quale)."""
    import estratti_conto
    giorno = giorno or date.today().isoformat()
    segnate = []
    for anno in (date.today().year - 1, date.today().year, date.today().year + 1):
        if not file_anno(anno).exists():
            continue
        libro, ws = _apri(anno)
        pos = _indici(ws)
        trovate = [r for r in righe(anno) if r["Stato"] != SALDATA and
                   (_stessa(r["Fornitore"], r["Numero Fattura"], fornitore, numero) if numero else
                    estratti_conto.stesso_fornitore(str(r["Fornitore"] or ""), fornitore, alias={}))]
        if not numero and len(trovate) > 1:
            return (f"{fornitore} ha {len(trovate)} righe da pagare: dimmi il numero della fattura "
                    f"({', '.join(str(r['Numero Fattura']) for r in trovate)}).")
        for r in trovate:
            ws.cell(row=r["riga"], column=pos["Stato"] + 1, value=SALDATA)
            nota = ws.cell(row=r["riga"], column=pos["Note"] + 1)
            nota.value = "; ".join(filter(None, [nota.value, f"saldata il {date.fromisoformat(giorno):%d/%m/%Y}"]))
            segnate.append(f"{r['Fornitore']} n. {r['Numero Fattura']}" + (f" ({r['Rata']})" if r["Rata"] else ""))
        if trovate:
            try:
                libro.save(file_anno(anno))
            except PermissionError:
                return f"Il file {file_anno(anno).name} è aperto: chiudilo e ridimmelo."
    if not segnate:
        return f"Non trovo nello scadenziario fatture da pagare di {fornitore}" + (f" n. {numero}." if numero else ".")
    return "Segnate come saldate: " + "; ".join(segnate) + "."


def da_pagare(entro: Optional[str] = None) -> list:
    """Righe ancora da pagare (con scadenza entro quella data, se indicata), in ordine di scadenza."""
    elenco = [r for anno in (date.today().year - 1, date.today().year, date.today().year + 1)
              for r in righe(anno) if r["Stato"] != SALDATA]
    if entro:
        limite = date.fromisoformat(entro)
        elenco = [r for r in elenco if r["Data di Scadenza"] and _giorno(r["Data di Scadenza"]) <= limite]
    return sorted(elenco, key=lambda r: _giorno(r["Data di Scadenza"]) or date.max)


def _giorno(valore):
    return valore.date() if hasattr(valore, "date") and callable(valore.date) else valore


def testo_scadenze(righe_da_pagare: list, oggi: Optional[date] = None) -> str:
    """Messaggio per la chat: prima le GIÀ SCADUTE, poi quelle in arrivo; importi come li scrive l'amministrazione."""
    import registro_fatture as reg
    oggi = oggi or date.today()

    def riga(r):
        importo = reg.centesimi_in_euro(round(r["Importo EURO"] * 100)) if r["Importo EURO"] is not None else "importo ?"
        return (f"- {_giorno(r['Data di Scadenza']):%d/%m/%Y} {r['Fornitore']} n. {r['Numero Fattura']}: {importo}"
                + (f" ({r['Rata']})" if r["Rata"] else ""))
    scadute = [r for r in righe_da_pagare if r["Data di Scadenza"] and _giorno(r["Data di Scadenza"]) < oggi]
    in_arrivo = [r for r in righe_da_pagare if r not in scadute]
    parti = []
    if scadute:
        parti.append("GIÀ SCADUTE (ancora da pagare):\n" + "\n".join(riga(r) for r in scadute))
    if in_arrivo:
        parti.append("Da pagare nei prossimi 15 giorni:\n" + "\n".join(riga(r) for r in in_arrivo))
    return "\n\n".join(parti) or "Nessuna fattura da pagare nei prossimi 15 giorni."


# ---------------------------------------------------------------------------
# DA UNA FATTURA LETTA A UNA VOCE DELLO SCADENZIARIO
# ---------------------------------------------------------------------------
def leggi_nota(nota: Optional[str]) -> dict:
    """
    Quello che l'amministrazione scrive insieme alla fattura, senza modello:
      "scade il 15/11/2026"                     -> scadenza
      "60% a 7 gg DF e 40% a 30 gg FM"          -> rate
      "30 gg FM"                                -> termine solo per questa fattura
    """
    if not nota:
        return {}
    letto = {}
    rate = termini.leggi_rate(nota)
    if rate:
        letto["rate"] = rate
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?\b", nota)
    if m and not rate:
        anno = int(m.group(3)) if m.group(3) else date.today().year
        anno += 2000 if anno < 100 else 0
        try:
            letto["scadenza"] = date(anno, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    if not rate and "scadenza" not in letto and termini.leggi_termine(nota):
        letto["termine"] = re.search(r"\d+\s*(?:gg|giorni)\.?\s*[A-Za-z. ]{0,8}", nota, re.I).group(0).strip()
    return letto


def voce_da_fattura(fattura: dict, nota_utente: Optional[str] = None) -> dict:
    """
    Fattura letta (+ nota dell'amministrazione) -> voce dello scadenziario.
    Ordine: scadenza o rate dette in chat -> regola del fornitore (dati/regole_scadenze.json) -> scadenza sulla fattura
    -> termini del fornitore. Per le estere il controvalore è al cambio BdI del giorno della fattura.
    """
    import cambi_bdi
    import elabora_mese
    from fatture_comuni import piva_cliente_presente
    nota = leggi_nota(nota_utente)
    voce = {"fornitore": fattura.get("fornitore"), "numero": fattura.get("numero"),
            "data_emissione": fattura.get("data_emissione") or fattura.get("fine_periodo"),
            "valuta": fattura.get("valuta") or "EUR", "importo_valuta": elabora_mese._euro(fattura.get("totale_cent")),
            "note": []}
    if fattura.get("tipo_documento") == "nota_di_credito" and voce["importo_valuta"] is not None:
        voce["importo_valuta"] = -abs(voce["importo_valuta"])
    if fattura.get("tipo_documento") == "proforma":
        voce["note"].append("pro-forma: la fattura vera arriverà dopo")
    if piva_cliente_presente(fattura.get("testo")) is False:
        voce["note"].append("manca la nostra partita IVA sulla fattura: chiedere al fornitore di correggerla")
    voce["importo_eur"] = voce["importo_valuta"]
    if voce["valuta"] != "EUR" and voce["importo_valuta"] is not None and voce["data_emissione"]:
        q = cambi_bdi.quotazione(voce["valuta"], voce["data_emissione"])
        voce["importo_eur"] = (voce["importo_valuta"] / q[0]).quantize(Decimal("0.01")) if q else None
        voce["note"].append(f"cambio BdI {q[0]} del {date.fromisoformat(q[1]):%d/%m/%Y}" if q else "cambio non trovato")

    totale_cent = fattura.get("totale_cent")
    rate = nota.get("rate") or termini.regola_per(voce["fornitore"], fattura.get("testo") or "")
    if rate and voce["data_emissione"] and totale_cent:
        voce["rate"] = termini.piano_di_pagamento(voce["data_emissione"], abs(totale_cent), rate)
        if voce["importo_valuta"] is not None and voce["importo_valuta"] < 0:
            for r in voce["rate"]:
                r["importo_cent"] = -r["importo_cent"]
        voce["termine"] = " + ".join(f"{r['percentuale']}% {r['termine']}" for r in rate)
        voce["note"].append("rate dette in chat" if nota.get("rate") else "rate dalla regola del fornitore")
    elif nota.get("scadenza"):
        voce["scadenza"], voce["termine"] = nota["scadenza"], termini.termine_di(voce["fornitore"] or "")
        voce["note"].append("scadenza detta in chat")
    elif nota.get("termine") and voce["data_emissione"]:
        voce["termine"] = nota["termine"]
        voce["scadenza"] = termini.calcola_scadenza(voce["data_emissione"], nota["termine"])
    else:
        voce["scadenza"], fonte = elabora_mese.scadenza(fattura | {"data_emissione": voce["data_emissione"]})
        voce["termine"] = termini.termine_di(voce["fornitore"] or "")
        if fonte != "dalla fattura":
            voce["note"].append(fonte)
    return voce
