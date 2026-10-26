"""
ELABORAZIONE DI UN MESE DI FATTURE (invio "a blocchi")
======================================================

L'amministrazione mette tutte le fatture ESTERE del mese in una cartella (es. "10 Ottobre", entro il 15 del
mese dopo), con gli estratti conto delle carte. Questo modulo:

  1. legge ogni PDF UNA volta sola (la lettura resta salvata in dati/letture/: rilanciare non costa);
  2. scarta le copie di cortesia quando c'è l'originale, e i documenti che non sono fatture
     (contabili di bonifico, avvisi, guide);
  3. per le fatture ESTERE calcola il controvalore in euro: carta Amex -> carta UniCredit -> cambio BdI;
  4. data di registrazione = ultimo giorno lavorativo del MESE DEL BLOCCO (anche per le fatture arrivate
     in ritardo, es. una di settembre nel blocco di ottobre);
  5. aggiorna l'anagrafica dei fornitori esteri e mette le modifiche nella colonna Note; segnala se manca
     la nostra partita IVA sulla fattura;
  6. scrive NELLA CARTELLA DEL MESE, nel layout dell'amministrazione:
       - Registrazione contabile (fogli: registrazione, pagate con carta, non nello scadenziario)
         (ratei e risconti si calcolano a parte, a una data di chiusura: ratei_risconti.py)
       - un riepilogo di cosa va controllato a mano.

Lo scadenziario NON si tocca (regola del 26/10): si alimenta solo con le fatture mandate per lo scadenziario.
Il blocco elenca soltanto le fatture che non sono nello scadenziario e non sono pagate con carta, per
accorgersi di una fattura sfuggita.

Il modello legge (punto 1); tutto il resto è Python.
Uso:  python app/elabora_mese.py CARTELLA [--amex FILE.xlsx] [--unicredit FILE.pdf] [--mese MM-AAAA]
"""

import argparse
import hashlib
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

import anagrafica_esteri
import cambi_bdi
import config
import estratti_conto as ec
import scadenziario
import termini
from estrazione import ErroreEstrazione, ServizioNonDisponibile, estrai_da_file
from fatture_comuni import PIVA_ESTERO_ASSENTE, e_estero, piva_cliente_presente

LETTURE = config.DATI / "letture"
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
CENT = Decimal("0.01")
# Parole che, nel nome di un file, indicano una contabile o un documento che NON è una fattura
# (in prova: "First instalment 4411 and full payment 4410.pdf", "Wire Transfer NWD 18.pdf").
NON_FATTURE = re.compile(r"\b(bonifico|contabile|guide|guida|avviso|estratto|statement|payment|instalment|"
                         r"installment|wire|transfer|remittance)\b", re.I)


# ---------------------------------------------------------------------------
# 1. LETTURA (con memoria: ogni file si legge una volta sola)
# ---------------------------------------------------------------------------
def _versione_lettura() -> str:
    """
    Cambia SOLO quando cambia quello che chiediamo al modello: istruzioni (che contengono anche il nome
    dell'azienda, dal .env) e schema dei campi. Si salva la sua risposta "grezza"; le conversioni Python
    (date, importi, partite IVA) si rifanno a ogni avvio. Così correggere Python non costa una nuova lettura.
    """
    import fatture_comuni
    domanda = config.MODELLO_TESTO + config.MODELLO_FOTO + fatture_comuni.ISTRUZIONI_ESTRAZIONE + json.dumps(fatture_comuni.DatiFattura.model_json_schema(),
                                                                sort_keys=True)
    return hashlib.sha256(domanda.encode()).hexdigest()[:8]


def _impronta(percorso: Path) -> str:
    return f"{hashlib.sha256(percorso.read_bytes()).hexdigest()[:20]}-{_versione_lettura()}"


def leggi(percorso: Path) -> dict:
    LETTURE.mkdir(parents=True, exist_ok=True)
    salvata = LETTURE / f"{_impronta(percorso)}.json"
    if salvata.exists():
        memoria = json.loads(salvata.read_text(encoding="utf-8"))
        if "errore" in memoria:
            return memoria | {"file": percorso.name}
        dati = estrai_da_file(percorso, grezzo=memoria["_grezzo"],      # niente chiamata al modello
                              grezzo_foto=memoria.get("_grezzo_foto"))
        if "_grezzo_foto" in dati and "_grezzo_foto" not in memoria:   # immagine letta ora: si salva anche lei
            salvata.write_text(json.dumps(memoria | {"_grezzo_foto": dati["_grezzo_foto"]}, ensure_ascii=False,
                                          indent=1), encoding="utf-8")
    else:
        try:
            dati = estrai_da_file(percorso)
        except ServizioNonDisponibile as errore:          # temporaneo: niente salvataggio, si riprova
            return {"errore": str(errore), "file": percorso.name}
        except ErroreEstrazione as errore:
            dati = {"errore": str(errore)}
        da_salvare = {c: dati[c] for c in ("_grezzo", "_grezzo_foto") if c in dati} if "_grezzo" in dati else dati
        salvata.write_text(json.dumps(da_salvare,
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    dati["file"] = percorso.name
    return dati


def file_da_leggere(cartella: Path, esclusi: set) -> list:
    """Tutti i PDF, senza le copie di cortesia che hanno anche l'originale e senza gli estratti conto."""
    pdf = [p for p in sorted(cartella.rglob("*")) if p.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png")
           and p.resolve() not in esclusi and "risultati" not in p.parts]
    originali = {re.sub(r"\s*\(copia di cortesia.*?\)", "", p.stem, flags=re.I).lower() for p in pdf
                 if "copia di cortesia" not in p.stem.lower()}
    scelti, saltati = [], []
    for p in pdf:
        base = re.sub(r"\s*\(copia di cortesia.*?\)", "", p.stem, flags=re.I).lower()
        if "copia di cortesia" in p.stem.lower() and base in originali:
            saltati.append((p, "copia di cortesia (c'è l'originale)"))
        elif NON_FATTURE.search(p.stem) and " ft n" not in p.stem.lower():
            saltati.append((p, "non è una fattura (dal nome del file)"))
        else:
            scelti.append(p)
    # Prima i file che si chiamano come fatture ("... ft n. ..."): se la stessa fattura compare anche in un
    # altro documento, vince la fattura.
    scelti.sort(key=lambda p: (" ft n" not in p.stem.lower() and "nota di credito" not in p.stem.lower(), str(p)))
    return scelti, saltati


# ---------------------------------------------------------------------------
# 2. REGOLE
# ---------------------------------------------------------------------------
def _euro(centesimi: Optional[int]) -> Optional[Decimal]:
    return None if centesimi is None else (Decimal(centesimi) / 100).quantize(CENT)


def carta_indicata(metodo: Optional[str]) -> Optional[str]:
    """Dal metodo di pagamento scritto sulla fattura: quale estratto conto guardare per primo."""
    m = (metodo or "").lower()
    if "american express" in m or "amex" in m:
        return "amex"
    if "mastercard" in m or "visa" in m:
        return "unicredit"
    return None


def numeri_compatibili(a: Optional[str], b: Optional[str]) -> bool:
    """Stesso numero di fattura, anche con zeri iniziali o separatori diversi ('0031415926' = '31415926').
    Se uno dei due manca, potrebbe essere la stessa fattura."""
    na, nb = (re.sub(r"[^0-9a-z]", "", (n or "").lower()).lstrip("0") for n in (a, b))
    return not na or not nb or na == nb


def pagamento_in_euro(fattura: dict, movimenti: list, usati: set):
    """Fattura in euro pagata con carta: addebito con lo stesso importo e lo stesso fornitore."""
    importo = _euro(fattura.get("totale_cent"))
    if importo is None or not fattura.get("data_emissione"):
        return None
    giorno = date.fromisoformat(fattura["data_emissione"])
    candidati = [m for m in movimenti if id(m) not in usati and m.importo_valuta is None and m.importo_eur == importo
                 and abs((m.data - giorno).days) <= 45
                 and ec.stesso_fornitore(fattura.get("fornitore") or "", m.descrizione)]
    if not candidati:
        return None
    migliore = min(candidati, key=lambda m: abs((m.data - giorno).days))
    usati.add(id(migliore))
    return migliore


def controvalore(fattura: dict, tutti: list, usati: set) -> tuple:
    """(importo in euro, fonte, movimento). Per le fatture in euro cerca solo se sono state pagate con carta."""
    importo = _euro(fattura.get("totale_cent"))
    movimenti = [m for m in tutti if m.importo_valuta is not None]
    if fattura.get("valuta") in (None, "EUR"):
        return importo, "in euro", pagamento_in_euro(fattura, tutti, usati)
    if importo is None or not fattura.get("data_emissione"):
        return None, "importo o data della fattura mancanti: controvalore da calcolare a mano", None
    ricerca = {"fornitore": fattura.get("fornitore") or "", "valuta": fattura["valuta"],
               "importo_valuta": importo, "data_emissione": fattura["data_emissione"]}
    preferita = carta_indicata(fattura.get("metodo_pagamento"))
    gruppi = [[m for m in movimenti if m.fonte == preferita], movimenti] if preferita else [movimenti]
    for gruppo in gruppi:
        trovato = ec.abbina(ricerca, gruppo, gia_usati=usati)
        if trovato:
            return trovato.controvalore_eur, f"{trovato.fonte} (cambio {trovato.cambio}, del {trovato.data:%d/%m})", trovato
    q = cambi_bdi.quotazione(fattura["valuta"], fattura["data_emissione"])
    if q is None:
        return None, "CAMBIO NON TROVATO", None
    return (importo / q[0]).quantize(CENT, ROUND_HALF_UP), f"cambio BdI {q[0]} del {date.fromisoformat(q[1]):%d/%m}", None


def nota_anagrafica(testo: str) -> str:
    """Nota breve per la colonna Note della registrazione (quello che serve all'amministrazione)."""
    nuovo = re.match(r"Creata la scheda anagrafica di .+ \(verifica partita IVA: (.+)\)\.", testo)
    if nuovo:
        return f"nuovo fornitore: creare l'anagrafica (P.IVA {nuovo.group(1)})"
    return testo.split(": ", 1)[-1].rstrip(".")       # "Rossi: nome cambiato da ..." -> "nome cambiato da ..."


def scadenza(fattura: dict) -> tuple:
    """(data di scadenza, da dove arriva)."""
    termine = termini.termine_di(fattura.get("fornitore") or "")
    scritta = fattura.get("data_scadenza")
    # Una "scadenza" uguale alla data fattura spesso vuol dire "non indicata" (es. fattura SDI con scadenza
    # alla data del documento): se il fornitore ha dei termini, valgono quelli (come fa l'amministrazione).
    if scritta and not (termine and scritta == fattura.get("data_emissione")):
        return scritta, "dalla fattura"
    if termine and fattura.get("data_emissione"):
        return termini.calcola_scadenza(fattura["data_emissione"], termine), f"termini {termine}"
    return None, "termini di pagamento da definire"


# ---------------------------------------------------------------------------
# 3. ELABORAZIONE DEL MESE
# ---------------------------------------------------------------------------
def mese_della_cartella(cartella: Path, oggi: Optional[date] = None) -> Optional[str]:
    """
    "10 Ottobre" -> "10-2026" (o "Ottobre 2026", "2026-10"). Senza anno: è l'ultimo mese con quel nome
    già passato (il blocco di dicembre si elabora a gennaio dell'anno dopo).
    """
    nome, oggi = cartella.name.lower(), oggi or date.today()
    anno = re.search(r"\b(20\d{2})\b", nome)
    numero = next((i + 1 for i, m in enumerate(MESI) if m in nome), None)
    if numero is None:
        cifre = re.search(r"\b(\d{1,2})\b", re.sub(r"\b20\d{2}\b", "", nome))
        numero = int(cifre.group(1)) if cifre and 1 <= int(cifre.group(1)) <= 12 else None
    if numero is None:
        return None
    anno = int(anno.group(1)) if anno else (oggi.year if numero <= oggi.month else oggi.year - 1)
    return f"{numero:02d}-{anno}"


def elabora(cartella: Path, amex: Optional[Path] = None, unicredit: Optional[Path] = None,
            mese: Optional[str] = None) -> dict:
    """mese 'MM-AAAA' del blocco (per la data di registrazione); se manca, dal nome della cartella."""
    mese = mese or mese_della_cartella(cartella)
    esclusi = {p.resolve() for p in (amex, unicredit) if p}
    da_leggere, saltati = file_da_leggere(cartella, esclusi)
    movimenti = (ec.leggi_amex(amex) if amex else []) + (ec.leggi_unicredit(unicredit) if unicredit else [])
    in_valuta = [m for m in movimenti if m.importo_valuta is not None]
    usati, fatture, viste = set(), [], set()

    for percorso in da_leggere:
        f = leggi(percorso)
        f["percorso"] = str(percorso.relative_to(cartella))
        if f.get("errore"):
            saltati.append((percorso, f["errore"]))
            continue
        if f.get("tipo_documento") == "altro":
            saltati.append((percorso, "non è una fattura (secondo la lettura)"))
            continue
        chiave = (re.sub(r"\W", "", (f.get("partita_iva") or f.get("fornitore") or "").lower()),
                  re.sub(r"\W", "", (f.get("numero") or "").lower()))
        if chiave in viste:
            saltati.append((percorso, "stessa fattura già letta da un altro file"))
            continue
        # Stessa fattura con numero letto diverso (in prova: "... ft n. 1 - NEW.pdf" accanto all'originale):
        # stesso fornitore, stessa data e stesso importo -> un solo documento, si completano i dati mancanti.
        # ATTENZIONE: servono anche numeri compatibili. Due abbonamenti dello stesso giorno e importo
        # (Fabrikam, 2 x 15 USD il 21/09) sono due fatture diverse.
        gemella = next((g for g in fatture if g.get("data_emissione") == f.get("data_emissione")
                        and g.get("totale_cent") == f.get("totale_cent") and f.get("totale_cent")
                        and numeri_compatibili(g.get("numero"), f.get("numero"))
                        and ec.stesso_fornitore(g.get("fornitore") or "", f.get("fornitore") or "", alias={})), None)
        if gemella:
            for campo, valore in f.items():
                if gemella.get(campo) in (None, "") and valore not in (None, ""):
                    gemella[campo] = valore
            gemella["note"].append(f"documento presente due volte ({percorso.name})")
            saltati.append((percorso, f"doppione di {gemella['percorso']}"))
            continue
        viste.add(chiave)
        if not f.get("data_emissione") and f.get("fine_periodo"):
            f["data_emissione"] = f["fine_periodo"]
            f.setdefault("note_lettura", []).append("data fattura = fine del periodo di fatturazione")
        f["estera"] = e_estero(f.get("paese_fornitore")) and not f.get("formato_sdi")
        if f["estera"] and not f.get("partita_iva"):
            f["partita_iva"] = PIVA_ESTERO_ASSENTE
        segno = -1 if f.get("tipo_documento") == "nota_di_credito" else 1
        f["importo_valuta"] = _euro(f.get("totale_cent"))
        f["importo_eur"], f["fonte_cambio"], mov = controvalore(f, movimenti, usati)
        if mov:
            f["movimento"] = mov.per_json()
        if segno < 0:
            f["importo_valuta"] = -abs(f["importo_valuta"]) if f["importo_valuta"] is not None else None
            f["importo_eur"] = -abs(f["importo_eur"]) if f["importo_eur"] is not None else None
        if mese or f.get("data_emissione"):
            f["data_registrazione"] = termini.data_registrazione(mese or f["data_emissione"])
        f["scadenza"], f["fonte_scadenza"] = scadenza(f)
        if not f["scadenza"] and mov:                 # pagata con carta: la "scadenza" è il giorno dell'addebito
            f["scadenza"], f["fonte_scadenza"] = mov.data.isoformat(), "addebito su carta"
        # Solo per la scadenza scritta sulla fattura: un addebito su carta può venire prima (es. volo pagato
        # alla prenotazione), e non è un errore.
        if f["fonte_scadenza"] == "dalla fattura" and f.get("data_emissione") and f["scadenza"] < f["data_emissione"]:
            f.setdefault("note_lettura", []).append("scadenza precedente alla data fattura: controllare")
        f["note"] = list(f.get("note_lettura", []))
        if piva_cliente_presente(f.get("testo")) is False:
            f["note"].append("manca la nostra partita IVA sulla fattura: chiedere al fornitore di correggerla")
        # Solo un controllo: lo scadenziario non si modifica dal blocco.
        f["nello_scadenziario"] = bool(f.get("movimento")) or f.get("tipo_documento") == "nota_di_credito" or \
            scadenziario.contiene(f.get("fornitore"), f.get("numero"))
        if f["estera"]:
            try:
                cambiati = anagrafica_esteri.aggiorna_da_fattura(
                    f | {"id": f["file"], "data_emissione": f.get("data_emissione") or ""})
                f["note"] += [nota_anagrafica(n) for n in cambiati if "cambiato" in n or "Creata" in n
                              or "da controllare" in n]
            except Exception as errore:
                f["note"].append(f"anagrafica non aggiornata ({errore})")
        fatture.append(f)

    if mese:                                # per ratei e risconti, calcolati a parte (ratei_risconti.py)
        # Anche le italiane (regola del 26/10): non vanno nella registrazione, ma contano per ratei e risconti.
        import ratei_risconti
        ratei_risconti.salva_blocco(mese, [f for f in fatture if f.get("tipo_documento") != "proforma"])
    return {"fatture": fatture, "saltati": saltati, "movimenti": movimenti, "mese": mese}


# ---------------------------------------------------------------------------
# 4. FILE IN USCITA (layout dell'amministrazione)
# ---------------------------------------------------------------------------
def _data_it(iso: Optional[str]):
    return date.fromisoformat(iso) if iso else None


def scrivi_file(risultato: dict, uscita: Path, mese: str) -> list:
    """
    Nella cartella del mese: la registrazione contabile e il riepilogo. Niente scadenziario e niente copie degli
    estratti conto (regola del 26/10: gli estratti li ha già l'amministrazione).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    uscita.mkdir(parents=True, exist_ok=True)
    creati = []

    def foglio(ws, intestazione, righe):
        ws.append(intestazione)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in righe:
            ws.append(r)
        for colonna in ws.columns:
            ws.column_dimensions[colonna[0].column_letter].width = min(55, max(12, *(len(str(c.value or "")) + 2 for c in colonna)))
            for c in colonna[1:]:
                if isinstance(c.value, date):
                    c.number_format = "DD/MM/YYYY"
                elif isinstance(c.value, (float, Decimal)):
                    c.number_format = "#,##0.00"

    def numero(valore):
        return float(valore) if valore is not None else None

    # La pro-forma è una richiesta di pagamento: NON va nella registrazione contabile
    # (regola presa dai file dell'amministrazione).
    estere = sorted([f for f in risultato["fatture"] if f["estera"] and f.get("tipo_documento") != "proforma"],
                    key=lambda f: (f.get("fornitore") or "").lower())
    wb = Workbook()
    foglio(wb.active, ["Data Registrazione", "Fornitore", "Numero Fattura", "Data Fattura",
                       "Importo Valuta Originaria", "Importo EURO", "Note"],
           [[_data_it(f.get("data_registrazione")), f.get("fornitore"), f.get("numero"), _data_it(f.get("data_emissione")),
             numero(f["importo_valuta"]), numero(f["importo_eur"]), "; ".join(f["note"]) or None] for f in estere])
    wb.active.title = "Registrazione Contabile"

    # Per analisi (l'amministrazione lo vuole tenere): le fatture addebitate su carta, con il giorno dell'addebito.
    con_carta = [f for f in risultato["fatture"] if f.get("movimento")]
    foglio(wb.create_sheet("Pagate con carta"),
           ["Fornitore", "Numero Fattura", "Data Fattura", "Importo Valuta Originaria", "Valuta", "Importo EURO",
            "Carta", "Data addebito"],
           [[f.get("fornitore"), f.get("numero"), _data_it(f.get("data_emissione")), numero(f["importo_valuta"]),
             f.get("valuta"), numero(f["importo_eur"]), f["movimento"]["fonte"].upper(),
             _data_it(f["movimento"]["data"])] for f in con_carta])

    # Solo un controllo, lo scadenziario resta com'è: fatture da pagare che lì non ci sono.
    mancanti = [f for f in risultato["fatture"] if not f.get("nello_scadenziario")]
    foglio(wb.create_sheet("Non nello scadenziario"),
           ["Fornitore", "Numero Fattura", "Data Fattura", "Importo Valuta Originaria", "Valuta", "Importo EURO",
            "Scadenza calcolata", "Da dove"],
           [[f.get("fornitore"), f.get("numero"), _data_it(f.get("data_emissione")), numero(f["importo_valuta"]),
             f.get("valuta"), numero(f["importo_eur"]), _data_it(f.get("scadenza")), f.get("fonte_scadenza")]
            for f in mancanti])
    creati.append(uscita / f"Registrazione contabile fatture estere {mese}.xlsx")
    wb.save(creati[-1])

    righe = [f"Elaborazione {mese}: {len(risultato['fatture'])} fatture ({len(estere)} da registrare), "
             f"{len(risultato['saltati'])} file saltati.",
             f"Data di registrazione: {_data_it(termini.data_registrazione(mese)):%d/%m/%Y}." if risultato.get("mese") else "",
             "", "DA CONTROLLARE A MANO:"]
    for f in risultato["fatture"]:
        problemi = []
        if f["estera"] and f["importo_eur"] is None:
            problemi.append("controvalore in euro mancante")
        if not f.get("numero") or not f.get("data_emissione"):
            problemi.append("numero o data mancanti")
        if any("partita IVA" in n and "nostra" in n for n in f["note"]):
            problemi.append("manca la nostra partita IVA")
        if problemi:
            righe.append(f"- {f['percorso']}: {', '.join(problemi)}")
    righe += ["", "NON NELLO SCADENZIARIO E NON PAGATE CON CARTA (controllare se sono sfuggite):"] + [
        f"- {f.get('fornitore')} n. {f.get('numero')} del {_data_it(f.get('data_emissione')) or '?'}"
        for f in mancanti] + (["- nessuna"] if not mancanti else [])
    righe += ["", "FILE SALTATI:"] + [f"- {p.name}: {motivo}" for p, motivo in risultato["saltati"]]
    righe += ["", "CONTROVALORI DELLE FATTURE ESTERE:"] + [
        f"- {f.get('fornitore')} n. {f.get('numero')}: {f.get('importo_valuta')} {f.get('valuta')} -> "
        f"{f.get('importo_eur')} € ({f['fonte_cambio']})" for f in estere]
    creati.append(uscita / f"Riepilogo elaborazione {mese}.txt")
    creati[-1].write_text("\n".join(righe), encoding="utf-8")
    return creati


def main():
    parser = argparse.ArgumentParser(description="Elabora il blocco mensile delle fatture estere.")
    parser.add_argument("cartella", type=Path, help="cartella del mese, es. '.../10 Ottobre'")
    parser.add_argument("--amex", type=Path)
    parser.add_argument("--unicredit", type=Path)
    parser.add_argument("--uscita", type=Path, help="dove scrivere i file (di solito la cartella del mese)")
    parser.add_argument("--mese", help="MM-AAAA del blocco (di solito si ricava dal nome della cartella)")
    a = parser.parse_args()
    risultato = elabora(a.cartella, a.amex, a.unicredit, a.mese)
    mese = risultato["mese"] or date.today().strftime("%m-%Y")
    for p in scrivi_file(risultato, a.uscita or a.cartella, mese):
        print("creato:", p)


if __name__ == "__main__":
    main()
