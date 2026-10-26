"""Scadenziario annuale: aggiunta delle fatture, rate, "saldata", note dell'amministrazione (senza modello)."""

from decimal import Decimal

import pytest

import config
import scadenziario


@pytest.fixture(autouse=True)
def cartella_scadenziario(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CARTELLA_SCADENZIARIO", tmp_path)
    return tmp_path


def fattura(**altro):
    return {"fornitore": "Northwind BV", "numero": "INV-0042", "data_emissione": "2026-09-30", "valuta": "EUR",
            "totale_cent": 120000, "tipo_documento": "fattura", "testo": "Bill to Studio Prova IT01234567897"} | altro


def test_aggiunge_una_volta_sola_e_segna_saldata():
    voce = scadenziario.voce_da_fattura(fattura(), "scade il 15/11/2026")
    assert voce["scadenza"] == "2026-11-15" and voce["importo_eur"] == Decimal("1200.00")
    assert "Aggiunta" in scadenziario.aggiungi(voce)
    assert "già nello scadenziario" in scadenziario.aggiungi(voce)
    assert scadenziario.contiene("Northwind B.V.", "0042") is False          # numero diverso
    assert scadenziario.contiene("NORTHWIND BV", "INV-0042")
    assert len(scadenziario.da_pagare()) == 1
    assert "saldate" in scadenziario.segna_saldata("Northwind", "INV-0042")
    assert scadenziario.da_pagare() == []
    assert "Non trovo" in scadenziario.segna_saldata("Contoso")


def test_rate_del_fornitore_una_riga_per_rata(monkeypatch, tmp_path):
    import json
    import termini
    regole = tmp_path / "regole.json"
    regole.write_text(json.dumps([{"fornitore": "Contoso Media", "se_contiene": "chat", "rate": [
        {"percentuale": 60, "termine": "7 gg DF"}, {"percentuale": 40, "termine": "30 gg FM"}]}]))
    monkeypatch.setattr(termini, "REGOLE", regole)
    voce = scadenziario.voce_da_fattura(fattura(fornitore="Contoso Media Srl", numero="77",
                                                testo="Servizio chat settembre IT01234567897"))
    assert [r["importo_cent"] for r in voce["rate"]] == [72000, 48000]
    scadenziario.aggiungi(voce)
    righe = scadenziario.righe(2026)
    assert [(r["Importo EURO"], r["Data di Scadenza"].date().isoformat()) for r in righe] == \
        [(720.0, "2026-10-07"), (480.0, "2026-10-31")]
    # Senza numero, con due rate aperte, il bot chiede quale fattura.
    assert "dimmi il numero" not in scadenziario.segna_saldata("Contoso Media", "77")


def test_messaggio_scadenze_con_le_gia_scadute():
    from datetime import date
    scadenziario.aggiungi(scadenziario.voce_da_fattura(fattura(), "scade il 12/10/2026"))
    scadenziario.aggiungi(scadenziario.voce_da_fattura(fattura(numero="INV-0043"), "scade il 30/10/2026"))
    testo = scadenziario.testo_scadenze(scadenziario.da_pagare(), oggi=date(2026, 10, 26))
    assert testo == ("GIÀ SCADUTE (ancora da pagare):\n- 12/10/2026 Northwind BV n. INV-0042: 1.200,00 €\n\n"
                     "Da pagare nei prossimi 15 giorni:\n- 30/10/2026 Northwind BV n. INV-0043: 1.200,00 €")


def test_rate_e_termini_detti_in_chat():
    voce = scadenziario.voce_da_fattura(fattura(), "50% a 30 gg DF, 50% a 60 gg DF")
    assert [r["scadenza"] for r in voce["rate"]] == ["2026-10-30", "2026-11-29"]
    voce = scadenziario.voce_da_fattura(fattura(), "30 gg FM")
    assert voce["scadenza"] == "2026-10-31"


def test_segnala_la_nostra_partita_iva_mancante():
    voce = scadenziario.voce_da_fattura(fattura(testo="Bill to Studio Prova"), "scade il 1/12/2026")
    assert any("manca la nostra partita IVA" in n for n in voce["note"])


def test_rispetta_le_colonne_aggiunte_a_mano():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Fornitore", "Numero Fattura", "Data Fattura", "Banca", "Data di Scadenza"])
    wb.active.append(["Contoso Ltd", "A1", None, "UniCredit", None])
    wb.save(scadenziario.file_anno(2026))
    scadenziario.aggiungi(scadenziario.voce_da_fattura(fattura(), "scade il 15/11/2026"))
    righe = scadenziario.righe(2026)
    assert righe[0]["Fornitore"] == "Contoso Ltd" and righe[1]["Fornitore"] == "Northwind BV"
    assert righe[1]["Data di Scadenza"].date().isoformat() == "2026-11-15"   # nella colonna già esistente


def test_mese_dal_nome_della_cartella():
    from datetime import date
    from pathlib import Path
    from elabora_mese import mese_della_cartella
    assert mese_della_cartella(Path("10 Ottobre"), oggi=date(2026, 11, 5)) == "10-2026"
    assert mese_della_cartella(Path("12 Dicembre"), oggi=date(2027, 1, 10)) == "12-2026"
    assert mese_della_cartella(Path("Gennaio 2027"), oggi=date(2027, 2, 3)) == "01-2027"
    assert mese_della_cartella(Path("fatture"), oggi=date(2027, 2, 3)) is None
