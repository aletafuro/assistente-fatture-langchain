"""Ratei e risconti a una data di chiusura, calcolati a parte con i blocchi salvati (senza modello)."""

from datetime import date
from decimal import Decimal

import pytest

import ratei_risconti as rr


@pytest.fixture(autouse=True)
def blocchi(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "BLOCCHI", tmp_path / "blocchi")


def test_rateo_fattura_di_gennaio_con_periodo_di_dicembre():
    # Esempio dell'amministrazione: fattura di gennaio 2027 "dal 15/12/2026 al 15/01/2027", chiusura 31/12/2026.
    # Il 15/01 è l'inizio del periodo dopo: il periodo vero è dal 15/12 al 14/01, 31 giorni (non 32).
    q = rr.quota_alla_data("2027-01-20", "2026-12-15", "2027-01-15", "320.00", "2026-12-31")
    assert (q["tipo"], q["giorni"], q["giorni_periodo"], str(q["quota"])) == ("rateo", 17, 31, "175.48")
    assert rr.nota(q) == "rateo: 175,48 € (17/31 giorni, dal 15/12/2026 al 31/12/2026)"
    # Fattura di febbraio "competenza dicembre 2026": tutta del periodo chiuso.
    q = rr.quota_alla_data("2027-02-05", "2026-12-01", "2026-12-31", "1000", "2026-12-31")
    assert q["giorni"] == q["giorni_periodo"] == 31 and str(q["quota"]) == "1000.00"


def test_annuale_dallo_stesso_giorno_allo_stesso_giorno():
    # "dal 15/11/2026 al 15/11/2027" = 365 giorni; con il 29/02 in mezzo (2027-2028) = 366.
    q = rr.quota_alla_data("2026-11-15", "2026-11-15", "2027-11-15", "365", "2026-12-31")
    assert (q["giorni_periodo"], q["al"], q["giorni"], str(q["quota"])) == (365, "2027-11-14", 318, "318.00")
    q = rr.quota_alla_data("2027-11-15", "2027-11-15", "2028-11-15", "366", "2027-12-31")
    assert q["giorni_periodo"] == 366


def test_risconto_a_fine_trimestre_e_nessuna_quota():
    # Abbonamento annuale pagato a settembre, situazione al 30/09: la parte da ottobre in poi si rinvia.
    q = rr.quota_alla_data("2026-09-17", "2026-09-17", "2027-09-16", "365", "2026-09-30")
    assert (q["tipo"], q["dal"], q["giorni"], str(q["quota"])) == ("risconto", "2026-10-01", 351, "351.00")
    assert rr.quota_alla_data("2026-09-30", "2026-09-01", "2026-09-30", "100", "2026-09-30") is None
    assert rr.quota_alla_data("2026-09-30", None, None, "100", "2026-09-30") is None
    assert rr.quota_alla_data("2026-10-05", "2026-10-01", "2026-10-31", "100", "2026-09-30") is None


def test_calcolo_dai_blocchi_salvati(tmp_path):
    rr.salva_blocco("12-2026", [{"fornitore": "Litware", "numero": "A1", "data_emissione": "2026-12-10",
                                 "inizio_periodo": "2026-12-10", "fine_periodo": "2027-01-09",
                                 "importo_eur": Decimal("310.00")}])
    rr.salva_blocco("01-2027", [{"fornitore": "Contoso", "numero": "B7", "data_emissione": "2027-01-20",
                                 "inizio_periodo": "2026-12-15", "fine_periodo": "2027-01-15",
                                 "importo_eur": Decimal("320.00")}])
    risultato = rr.calcola("2026-12-31")
    assert [(r["tipo"], r["fornitore"], str(r["quota"])) for r in risultato["righe"]] == \
        [("rateo", "Contoso", "175.48"), ("risconto", "Litware", "90.00")]
    assert risultato["blocchi"] == ["2026-12", "2027-01"]
    percorso = rr.scrivi_excel(risultato, tmp_path / "uscita")
    assert percorso.name == "Ratei e risconti al 31-12-2026.xlsx"
    assert "1 ratei e 1 risconti" in rr.messaggio(risultato)


def test_chiusura_predefinita_ultimo_trimestre():
    assert rr.chiusura_predefinita(date(2026, 10, 26)) == "2026-09-30"
    assert rr.chiusura_predefinita(date(2027, 2, 10)) == "2026-12-31"
    assert rr.chiusura_predefinita(date(2026, 3, 31)) == "2025-12-31"
