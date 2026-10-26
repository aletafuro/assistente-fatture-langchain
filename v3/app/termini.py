"""
DATE CONTABILI: data di registrazione, scadenze, termini di pagamento e rate
==========================================================================

Data di registrazione (regole dell'amministrazione):
   - è l'ULTIMO GIORNO LAVORATIVO DEL MESE CHE SI STA REGISTRANDO (il mese del blocco), anche se dentro c'è
     una fattura di un mese precedente arrivata in ritardo (es. fattura di settembre nel blocco di ottobre);
   - non lavorativi: sabato, domenica e i FESTIVI NAZIONALI ("i rossi del calendario").
     Es. gennaio 2027: 31 domenica, 30 sabato -> 29/01/2027.

Scadenza: quella scritta sulla fattura, se c'è. Altrimenti dai TERMINI DI PAGAMENTO del fornitore,
scritti come li scrive l'amministrazione:
    "30 gg DF"   -> 30 giorni dalla data fattura          "30 gg FM" -> 30 giorni, poi fine di quel mese
I termini stanno nel file Excel dell'amministrazione (FILE_TERMINI, su ownCloud), letto a ogni uso:
quello che lei aggiorna vale subito. I termini detti in chat vengono scritti anche in quel file.

Rate e casi speciali (dati/regole_scadenze.json), es. un fornitore che manda due fatture al mese: se la
fattura parla di "chat", 60% a 7 gg DF e 40% a 30 gg FM; se parla di "mail", tutta a 7 gg DF.

Ratei e risconti: in ratei_risconti.py (calcolo a una data di chiusura, a parte dalla registrazione).
"""

import calendar
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import config

TERMINI = config.DATI / "termini_pagamento.json"           # termini detti in chat (e copia di riserva)
REGOLE = config.DATI / "regole_scadenze.json"              # rate e casi speciali per fornitore
FILE_TERMINI = config.FILE_TERMINI                         # file Excel dell'amministrazione (se c'è)


# ---------------------------------------------------------------------------
# GIORNI LAVORATIVI E DATA DI REGISTRAZIONE
# ---------------------------------------------------------------------------
def _pasqua(anno: int) -> date:
    """Algoritmo di Gauss (calendario gregoriano)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = (h + l - 7 * m + 114) % 31 + 1
    return date(anno, mese, giorno)


def festivi(anno: int) -> set:
    """Festivi nazionali italiani ("i rossi del calendario"), Pasqua e Pasquetta comprese."""
    fissi = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
    pasqua = _pasqua(anno)
    return {date(anno, m, g) for m, g in fissi} | {pasqua, pasqua + timedelta(days=1)}


def lavorativo(giorno: date) -> bool:
    return giorno.weekday() < 5 and giorno not in festivi(giorno.year)


def data_registrazione(riferimento: str) -> str:
    """Ultimo giorno lavorativo del mese. riferimento: 'AAAA-MM-GG' (si usa il suo mese) o 'MM-AAAA'."""
    if re.fullmatch(r"\d{2}-\d{4}", riferimento):
        mese, anno = int(riferimento[:2]), int(riferimento[3:])
    else:
        giorno = date.fromisoformat(riferimento)
        mese, anno = giorno.month, giorno.year
    ultimo = date(anno, mese, calendar.monthrange(anno, mese)[1])
    while not lavorativo(ultimo):
        ultimo -= timedelta(days=1)
    return ultimo.isoformat()


# ---------------------------------------------------------------------------
# TERMINI DI PAGAMENTO
# ---------------------------------------------------------------------------
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


def _chiave(fornitore: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (fornitore or "").lower()))


def _dal_file_excel(percorso: Path) -> dict:
    """Termini dal file Excel dell'amministrazione: fornitore in prima colonna, termine nella cella con "NN gg"."""
    from openpyxl import load_workbook
    termini = {}
    for ws in load_workbook(percorso, read_only=True, data_only=False).worksheets:
        for riga in ws.iter_rows(min_row=2, values_only=True):
            if not riga or not riga[0] or not isinstance(riga[0], str):
                continue
            termine = next((c for c in riga[1:] if isinstance(c, str) and leggi_termine(c)), None)
            if termine:
                termini[_chiave(riga[0])] = {"fornitore": riga[0].strip(), "termine": termine.strip()}
    return termini


def carica() -> dict:
    """Termini detti in chat + termini del file dell'amministrazione (il file, aggiornato da lei, vince)."""
    termini = json.loads(TERMINI.read_text(encoding="utf-8")) if TERMINI.exists() else {}
    if FILE_TERMINI and FILE_TERMINI.exists():
        try:
            termini.update(_dal_file_excel(FILE_TERMINI))
        except Exception:
            pass                                    # file aperto o rovinato: valgono quelli già noti
    return termini


def _scrivi_nel_file(fornitore: str, termine: str) -> None:
    """Il termine detto in chat finisce anche nel file dell'amministrazione (riga nuova o aggiornata)."""
    from openpyxl import load_workbook
    libro = load_workbook(FILE_TERMINI)
    ws = libro.worksheets[0]
    intestazione = [c.value for c in ws[1]]
    colonna = next((i for i, v in enumerate(intestazione) if v and "termini" in str(v).lower()), 5)
    for riga in ws.iter_rows(min_row=2):                # stessa colonna che usa già lei, se diversa
        trovata = next((c.column - 1 for c in riga[1:] if isinstance(c.value, str) and leggi_termine(c.value)), None)
        if trovata is not None:
            colonna = trovata
            break
    for riga in ws.iter_rows(min_row=2):
        if riga[0].value and _chiave(str(riga[0].value)) == _chiave(fornitore):
            riga[colonna].value = termine
            break
    else:
        nuova = [None] * max(len(intestazione), colonna + 1)
        nuova[0], nuova[colonna] = fornitore, termine
        ws.append(nuova)
    libro.save(FILE_TERMINI)


def imposta(fornitore: str, termine: str) -> str:
    if leggi_termine(termine) is None:
        return f"Non capisco il termine '{termine}': scrivilo come '30 gg DF' o '30 gg FM'."
    salvati = json.loads(TERMINI.read_text(encoding="utf-8")) if TERMINI.exists() else {}
    salvati[_chiave(fornitore)] = {"fornitore": fornitore.strip(), "termine": termine.strip()}
    TERMINI.write_text(json.dumps(salvati, ensure_ascii=False, indent=2), encoding="utf-8")
    nota = ""
    if FILE_TERMINI and FILE_TERMINI.exists():
        try:
            _scrivi_nel_file(fornitore.strip(), termine.strip())
            nota = f" L'ho scritto anche nel file {FILE_TERMINI.name}."
        except PermissionError:
            nota = f" Il file {FILE_TERMINI.name} è aperto: l'ho ricordato io, aggiornalo quando lo chiudi."
    return f"Ricordato: {fornitore.strip()} si paga a {termine.strip()}.{nota}"


def termine_di(fornitore: str) -> Optional[str]:
    """Termine del fornitore, anche se il nome è scritto in modo un po' diverso ("Contoso Srl")."""
    termini = carica()
    chiave = _chiave(fornitore)
    if chiave in termini:
        return termini[chiave]["termine"]
    # Alias: la fattura di "Northwind Payments SA" per l'amministrazione è "Northwind"
    import estratti_conto
    for altro_nome, nome in estratti_conto.carica_alias().items():
        if estratti_conto.stesso_fornitore(nome, fornitore, alias={}) and _chiave(altro_nome) in termini:
            return termini[_chiave(altro_nome)]["termine"]
    generiche = {"srl", "spa", "s", "r", "l", "inc", "ltd", "llc", "gmbh", "bv", "the", "limited", "company"}
    parole = set(chiave.split()) - generiche
    for k, v in termini.items():
        if parole and parole & (set(k.split()) - generiche):
            return v["termine"]
    return None


def importa_da_excel(*percorsi) -> int:
    """
    Termini da Excel dell'amministrazione nel file della chat (usato per le prove: in produzione il file si legge
    direttamente). Negli scadenziari con formule tipo '=C5+30' il termine è 30 gg DF.
    """
    from openpyxl import load_workbook
    salvati, importati = (json.loads(TERMINI.read_text(encoding="utf-8")) if TERMINI.exists() else {}), 0
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
                    salvati[_chiave(riga[0])] = {"fornitore": riga[0].strip(), "termine": termine}
                    importati += 1
    TERMINI.write_text(json.dumps(salvati, ensure_ascii=False, indent=2), encoding="utf-8")
    return importati


# ---------------------------------------------------------------------------
# RATE E CASI SPECIALI
# ---------------------------------------------------------------------------
# Le regole sono dati dell'azienda, non codice. Formato di dati/regole_scadenze.json (esempio):
#   [{"fornitore": "Contoso Media", "se_contiene": "chat",
#     "rate": [{"percentuale": 60, "termine": "7 gg DF"}, {"percentuale": 40, "termine": "30 gg FM"}]},
#    {"fornitore": "Contoso Media", "se_contiene": "mail", "rate": [{"percentuale": 100, "termine": "7 gg DF"}]}]
def carica_regole() -> list:
    return json.loads(REGOLE.read_text(encoding="utf-8")) if REGOLE.exists() else []


def leggi_rate(testo: str) -> Optional[list]:
    """
    Rate scritte a parole: "60% a 7 gg DF e 40% a 30 gg FM" -> [{60, '7 gg DF'}, {40, '30 gg FM'}].
    Le percentuali devono fare 100. None se nel testo non ci sono rate.
    """
    trovate = re.findall(r"(\d{1,3})\s*%\s*(?:a|dopo|entro)?\s*(\d+\s*(?:gg|giorni)[^,;%]*?)(?=\s*(?:,|;|\be\b|$|\d{1,3}\s*%))",
                         testo or "", re.I)
    rate = [{"percentuale": int(p), "termine": t.strip()} for p, t in trovate if leggi_termine(t)]
    return rate if rate and sum(r["percentuale"] for r in rate) == 100 else None


def regola_per(fornitore: str, testo_fattura: str) -> Optional[list]:
    """Rate da applicare a questa fattura (regola del fornitore che corrisponde al testo), o None."""
    import estratti_conto
    for regola in carica_regole():
        if estratti_conto.stesso_fornitore(regola["fornitore"], fornitore or "", alias={}) and \
                regola["se_contiene"].lower() in (testo_fattura or "").lower():
            return regola["rate"]
    return None


def piano_di_pagamento(data_fattura: str, totale_cent: int, rate: list) -> list:
    """[{scadenza, importo_cent, descrizione}] per ogni rata; l'ultima prende i centesimi di arrotondamento."""
    piano, assegnati = [], 0
    for i, rata in enumerate(rate):
        quota = totale_cent - assegnati if i == len(rate) - 1 else round(totale_cent * rata["percentuale"] / 100)
        assegnati += quota
        piano.append({"scadenza": calcola_scadenza(data_fattura, rata["termine"]), "importo_cent": quota,
                      "descrizione": f"rata {i + 1}/{len(rate)}: {rata['percentuale']}% a {rata['termine']}"})
    return piano

