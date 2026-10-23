"""
CAMBI DELLA BANCA D'ITALIA - conversione in euro al cambio del GIORNO DELLA FATTURA
===================================================================================

Regola: si usa il cambio del GIORNO DI EMISSIONE della fattura (non quello di fine mese). Se quel giorno non c'è quotazione
(sabato, domenica, festivi), si usa l'ultima quotazione PRECEDENTE (fino a 8 giorni prima).

La Banca d'Italia pubblica la "quantità di valuta estera per 1 euro" (es. USD 1,1590):
   importo in euro = importo in valuta / quotazione

Niente cambio "di riserva" inventato (es. un 1,15 fisso): se il cambio non si trova,
la funzione restituisce None e il bot lo chiede all'utente.
I cambi già scaricati si salvano in dati/cambi_bdi.json, così non si richiedono ogni volta.
"""

import csv
import io
import json
import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import httpx

import config

log = logging.getLogger(__name__)

URL_BDI = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyTimeSeries"
GIORNI_INDIETRO = 8


def _carica_cache() -> dict:
    if config.CAMBI_BDI.exists():
        return json.loads(config.CAMBI_BDI.read_text(encoding="utf-8"))
    return {}


def _salva_cache(cache: dict) -> None:
    config.CAMBI_BDI.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")


def _scarica(valuta: str, dal: date, al: date) -> dict:
    """{'2026-09-01': '1.1590', ...} dal servizio REST della Banca d'Italia."""
    params = {"startDate": dal.isoformat(), "endDate": al.isoformat(),
              "baseCurrencyIsoCode": valuta, "currencyIsoCode": "EUR", "lang": "it"}
    risposta = httpx.get(URL_BDI, params=params, headers={"Accept": "text/csv"}, timeout=60)
    risposta.raise_for_status()
    righe = [r for r in risposta.text.splitlines() if r.strip() and not r.startswith("#")]
    tabella = list(csv.DictReader(io.StringIO("\n".join(righe))))
    if not tabella or "Quotazione" not in tabella[0]:
        return {}
    colonna_data = next(c for c in tabella[0] if c.startswith("Data"))
    return {r[colonna_data]: r["Quotazione"].replace(",", ".") for r in tabella
            if r["Quotazione"] not in (None, "", "N.D.")}


def quotazione(valuta: str, giorno: str) -> Optional[tuple]:
    """
    (quotazione, data_della_quotazione) per la valuta al giorno indicato (AAAA-MM-GG),
    oppure None se non si trova (servizio non raggiungibile, valuta sconosciuta...).
    """
    valuta = valuta.upper()
    if valuta == "EUR":
        return Decimal(1), giorno
    obiettivo = date.fromisoformat(giorno)
    cache = _carica_cache()
    serie = cache.setdefault(valuta, {})
    candidati = [(obiettivo - timedelta(days=i)).isoformat() for i in range(GIORNI_INDIETRO + 1)]

    if not any(g in serie for g in candidati) and obiettivo <= date.today():
        try:
            serie.update(_scarica(valuta, obiettivo - timedelta(days=GIORNI_INDIETRO), obiettivo))
            _salva_cache(cache)
        except Exception as errore:
            log.warning("Cambio BdI %s del %s non scaricato: %s", valuta, giorno, errore)
            return None
    for g in candidati:                      # il giorno stesso, poi i giorni precedenti
        if g in serie:
            return Decimal(serie[g]), g
    return None


def in_euro(centesimi_valuta: Optional[int], quota: Decimal) -> Optional[int]:
    """Centesimi in valuta -> centesimi di euro, arrotondati al centesimo (metà per eccesso)."""
    if centesimi_valuta is None:
        return None
    return int((Decimal(centesimi_valuta) / quota).to_integral_value(ROUND_HALF_UP))


def converti_fattura(dati: dict) -> dict:
    """
    Aggiunge ai dati: cambio_bdi, data_cambio e gli importi in euro (imponibile/iva/totale_eur_cent).
    Il totale in euro è imponibile + IVA convertiti (non il totale convertito a parte), così resta
    sempre coerente al centesimo. Se il cambio manca: cambio_bdi = None.
    """
    valuta = dati.get("valuta")
    risultato = {"cambio_bdi": None, "data_cambio": None,
                 "imponibile_eur_cent": None, "iva_eur_cent": None, "totale_eur_cent": None}
    if not valuta or not dati.get("data_emissione"):
        return risultato
    if dati.get("cambio_manuale"):                       # cambio scritto dall'utente
        quota, giorno = Decimal(dati["cambio_manuale"]), dati["data_emissione"]
    else:
        trovato = quotazione(valuta, dati["data_emissione"])
        if trovato is None:
            return risultato
        quota, giorno = trovato
    originali = [dati.get(c) for c in ("imponibile_cent", "iva_cent", "totale_cent")]
    imp, iva, tot = (in_euro(v, quota) for v in originali)
    if None not in originali and originali[0] + originali[1] == originali[2]:
        tot = imp + iva            # coerente in valuta -> coerente anche in euro, al centesimo
    return {"cambio_bdi": str(quota), "data_cambio": giorno,
            "imponibile_eur_cent": imp, "iva_eur_cent": iva, "totale_eur_cent": tot}
