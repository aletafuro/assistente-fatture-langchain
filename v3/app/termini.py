"""
DATE CONTABILI: data di registrazione e scadenza dai termini di pagamento
=========================================================================

Data di registrazione (regola dell'amministrazione): l'ULTIMO GIORNO DEL MESE della fattura;
se cade di sabato o domenica, il venerdì precedente. Es. gennaio 2027: 31 domenica, 30 sabato -> 29/01/2027.

Scadenza: quella scritta sulla fattura, se c'è. Altrimenti dai TERMINI DI PAGAMENTO del fornitore,
scritti come li scrive l'amministrazione:
    "30 gg DF"      -> 30 giorni dalla data fattura
    "60 gg DF"      -> 60 giorni dalla data fattura
    "30 gg FM"      -> 30 giorni dalla data fattura, poi fine di quel mese ("fine mese")
    "30 GG. D.F.F.M." -> come sopra
I termini per fornitore stanno in dati/termini_pagamento.json e si aggiornano dalla chat o da un Excel.
"""

import calendar
import json
import re
from datetime import date, timedelta
from typing import Optional

import config

TERMINI = config.DATI / "termini_pagamento.json"


def data_registrazione(data_fattura: str) -> str:
    giorno = date.fromisoformat(data_fattura)
    ultimo = date(giorno.year, giorno.month, calendar.monthrange(giorno.year, giorno.month)[1])
    while ultimo.weekday() >= 5:              # 5 = sabato, 6 = domenica
        ultimo -= timedelta(days=1)
    return ultimo.isoformat()


def leggi_termine(testo: str) -> Optional[tuple]:
    """'30 gg DF' -> (30, False); '30 GG. FM.' -> (30, True). None se non si capisce."""
    if not testo:
        return None
    t = str(testo).upper().replace(".", " ")
    m = re.search(r"(\d+)\s*(?:GG|GIORNI)", t)
    if not m:
        return None
    fine_mese = bool(re.search(r"\bF\s*M\b|FINE\s*MESE|DFFM|D\s*F\s*F\s*M", t))
    return int(m.group(1)), fine_mese


def calcola_scadenza(data_fattura: str, termine: str) -> Optional[str]:
    letto = leggi_termine(termine)
    if letto is None:
        return None
    giorni, fine_mese = letto
    scadenza = date.fromisoformat(data_fattura) + timedelta(days=giorni)
    if fine_mese:
        scadenza = date(scadenza.year, scadenza.month, calendar.monthrange(scadenza.year, scadenza.month)[1])
    return scadenza.isoformat()


# ---------------------------------------------------------------------------
# TERMINI PER FORNITORE
# ---------------------------------------------------------------------------
def _chiave(fornitore: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (fornitore or "").lower()))


def carica() -> dict:
    return json.loads(TERMINI.read_text(encoding="utf-8")) if TERMINI.exists() else {}


def imposta(fornitore: str, termine: str) -> str:
    if leggi_termine(termine) is None:
        return f"Non capisco il termine '{termine}': scrivilo come '30 gg DF' o '30 gg FM'."
    termini = carica()
    termini[_chiave(fornitore)] = {"fornitore": fornitore.strip(), "termine": termine.strip()}
    TERMINI.write_text(json.dumps(termini, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Ricordato: {fornitore.strip()} si paga a {termine.strip()}."


def termine_di(fornitore: str) -> Optional[str]:
    """Termine del fornitore, anche se il nome è scritto in modo un po' diverso ("Tailspin Srl")."""
    termini = carica()
    chiave = _chiave(fornitore)
    if chiave in termini:
        return termini[chiave]["termine"]
    # Alias: la fattura di "Northwind Payments SA" per l'amministrazione è "Northwind"
    import estratti_conto
    for altro_nome, nome in estratti_conto.carica_alias().items():
        if estratti_conto.stesso_fornitore(nome, fornitore, alias={}) and _chiave(altro_nome) in termini:
            return termini[_chiave(altro_nome)]["termine"]
    parole = set(chiave.split()) - {"srl", "spa", "s", "r", "l", "inc", "ltd", "llc", "gmbh", "bv", "the"}
    for k, v in termini.items():
        if parole and parole & (set(k.split()) - {"srl", "spa", "inc", "ltd", "llc", "gmbh"}):
            return v["termine"]
    return None


def importa_da_excel(*percorsi) -> int:
    """
    Termini da Excel dell'amministrazione: in ogni riga, il fornitore è la prima colonna e il termine è
    la cella che contiene "NN gg"; negli scadenziari con formule tipo '=C5+30' il termine è 30 gg DF.
    I file letti dopo prevalgono su quelli letti prima. Restituisce quanti fornitori sono stati importati.
    """
    from openpyxl import load_workbook
    termini, importati = carica(), 0
    for percorso in percorsi:
        for ws in load_workbook(percorso, read_only=True, data_only=False).worksheets:
            for riga in ws.iter_rows(min_row=2, values_only=True):
                if not riga or not riga[0] or not isinstance(riga[0], str):
                    continue
                termine = None
                for cella in riga[1:]:
                    if isinstance(cella, str) and leggi_termine(cella):
                        termine = cella
                    elif isinstance(cella, str) and re.fullmatch(r"=\s*\+?[A-Z]+\d+\s*\+\s*(\d+)", cella.strip()):
                        termine = f"{re.search(r'(\d+)$', cella.strip()).group(1)} gg DF"
                if termine:
                    termini[_chiave(riga[0])] = {"fornitore": riga[0].strip(), "termine": termine}
                    importati += 1
    TERMINI.write_text(json.dumps(termini, ensure_ascii=False, indent=2), encoding="utf-8")
    return importati
