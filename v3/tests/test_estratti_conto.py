"""Controvalore in euro dagli estratti conto delle carte (dati inventati, stesso formato di quelli veri)."""

from datetime import date
from decimal import Decimal

from openpyxl import Workbook

import estratti_conto as ec


def test_stringa_amex():
    d = ec.leggi_dettagli_amex("Foreign Spend Amount: 99.00 Dollari Statunitensi Commission Amount: 2.18 "
                               "Currency Exchange Rate: 1.1332")
    assert d == {"importo_valuta": Decimal("99.00"), "valuta": "USD", "commissioni": Decimal("2.18"),
                 "cambio": Decimal("1.1332")}


def test_stringa_amex_con_parti_in_ordine_diverso():
    d = ec.leggi_dettagli_amex("Currency Exchange Rate: 24.1654 Foreign Spend Amount: 46,887.00 "
                               "Corone Cecoslovacche Commission Amount: 48.51")
    assert d["valuta"] == "CZK" and d["importo_valuta"] == Decimal("46887.00") and d["cambio"] == Decimal("24.1654")


def test_riga_in_euro_non_ha_dettagli():
    assert ec.leggi_dettagli_amex("") is None


def _excel_amex(percorso):
    wb = Workbook()
    ws = wb.active
    ws.append(["Dettagli transazione", "Carta Business"])
    ws.append([])
    ws.append(["Data", "Descrizione", "Titolare", "Numero di Carta", "Importo", "Dettagli completi", "Riferimento", "Paese"])
    ws.append(["09/30/2026", "NORTHWIND.IO   NEW YORK", "MARIO ROSSI", "-11111", 89.54,
               "Foreign Spend Amount: 99.00 Dollari Statunitensi Commission Amount: 2.18 Currency Exchange Rate: 1.1332",
               "AT1", "UNITED STATES"])
    ws.append(["09/21/2026", "CODEPILOT   MOUNTAIN VIEW", "MARIO ROSSI", "-11111", 13.42,
               "Foreign Spend Amount: 15.00 Dollari Statunitensi Commission Amount: 0.33 Currency Exchange Rate: 1.1459",
               "AT2", "UNITED STATES"])
    ws.append(["09/12/2026", "CLOUDCO   DUBLIN", "MARIO ROSSI", "-11111", 18.85, "", "AT3", "IRELAND"])
    wb.save(percorso)


def test_lettura_excel_amex(tmp_path):
    _excel_amex(tmp_path / "amex.xlsx")
    movimenti = ec.leggi_amex(tmp_path / "amex.xlsx")
    assert len(movimenti) == 3
    m = movimenti[0]
    assert m.data == date(2026, 9, 30)                       # Amex scrive le date all'americana
    assert m.controvalore_eur == Decimal("87.36")           # 99 / 1,1332
    assert m.commissioni == Decimal("2.18")                 # 89,54 - 87,36
    assert movimenti[2].importo_valuta is None              # addebito già in euro


def test_abbinamento_per_importo_nome_e_alias(tmp_path):
    _excel_amex(tmp_path / "amex.xlsx")
    movimenti = ec.leggi_amex(tmp_path / "amex.xlsx")
    fattura = {"fornitore": "Northwind Inc.", "valuta": "USD", "importo_valuta": Decimal("99.00"),
               "data_emissione": "2026-09-30"}
    assert ec.abbina(fattura, movimenti).controvalore_eur == Decimal("87.36")
    # Sulla carta compare il nome del prodotto, non la ragione sociale: serve l'alias.
    altra = {"fornitore": "Exampletech Inc.", "valuta": "USD", "importo_valuta": Decimal("15.00"),
             "data_emissione": "2026-09-21"}
    assert ec.abbina(altra, movimenti) is not None          # unico movimento da 15 USD: si abbina lo stesso
    ec.aggiungi_alias("codepilot", "Exampletech")
    assert ec.stesso_fornitore("Exampletech Inc.", "CODEPILOT   MOUNTAIN VIEW")
    assert ec.stesso_fornitore("Exampletek Inc", "EXAMPLETECH INC")      # errore di battitura tollerato


def test_nessun_abbinamento_se_l_importo_non_coincide(tmp_path):
    _excel_amex(tmp_path / "amex.xlsx")
    fattura = {"fornitore": "Northwind Inc.", "valuta": "USD", "importo_valuta": Decimal("98.99"),
               "data_emissione": "2026-09-30"}
    assert ec.abbina(fattura, ec.leggi_amex(tmp_path / "amex.xlsx")) is None   # -> cambio Banca d'Italia


def test_riga_unicredit(monkeypatch):
    testo = ("14.09.26 H07371 Pagamento E-Commerce NORTHWIND AMSTERDAM 11.09.26 18,10 USD 1,15877 15,62 "
             "14.09.26 H07371 Commissione per cambio divisa estera NORTHWIND AMSTERDAM 11.09.26 0,27 "
             "16.09.26 H74788 Pagamento E-Commerce MUSICA LEEDS 14.09.26 6,99")
    import fatture_comuni
    monkeypatch.setattr(fatture_comuni, "leggi_pdf", lambda p: testo)
    movimenti = ec.leggi_unicredit("finto.pdf")
    assert len(movimenti) == 2
    assert movimenti[0].controvalore_eur == Decimal("15.62") and movimenti[0].commissioni == Decimal("0.27")
    assert movimenti[0].data == date(2026, 9, 11) and movimenti[1].importo_valuta is None
