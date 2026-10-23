"""Data di registrazione, scadenze dai termini e dal formato SDI (regole dell'amministrazione)."""

import pytest

import termini
from fatture_comuni import formato_sdi, scadenze_sdi


@pytest.mark.parametrize("fattura, registrazione", [
    ("2026-09-15", "2026-09-30"),     # 30/09/2026 è mercoledì
    ("2027-01-10", "2027-01-29"),     # esempio dell'amministrazione: 31 domenica, 30 sabato -> venerdì 29
    ("2026-10-02", "2026-10-30"),     # 31/10/2026 è sabato -> venerdì 30
    ("2026-02-03", "2026-02-27"),     # 28/02/2026 è sabato
])
def test_data_registrazione(fattura, registrazione):
    assert termini.data_registrazione(fattura) == registrazione


@pytest.mark.parametrize("termine, attesa", [
    ("30 gg DF", (30, False)), ("60 gg DF", (60, False)), ("BONIFICO B. 30 GG. FM.", (30, True)),
    ("60 gg D.F.F.M.", (60, True)), ("a vista", None),
])
def test_lettura_termini(termine, attesa):
    assert termini.leggi_termine(termine) == attesa


def test_calcolo_scadenza():
    assert termini.calcola_scadenza("2026-09-30", "30 gg DF") == "2026-10-30"
    assert termini.calcola_scadenza("2026-09-15", "30 gg FM") == "2026-10-31"


def test_termini_per_fornitore_con_nome_diverso():
    termini.imposta("Tailspin", "30 gg DF")
    assert termini.termine_di("Tailspin Srl") == "30 gg DF"
    assert termini.termine_di("Sconosciuto SpA") is None
    assert "Non capisco" in termini.imposta("Rossi", "presto")


SDI = """Cedente/prestatore (fornitore)
Identificativo fiscale ai fini IVA: IT03792180980
Cessionario/committente (cliente)
Modalità pagamento Dettagli Scadenze Importo
MP05 Bonifico IBAN IT97O0503455340000000007075
Data termine 15-09-2026 46gg"""


def test_formato_sdi_e_scadenza_con_giorni():
    assert formato_sdi(SDI)
    assert not formato_sdi("Invoice number 123 Bill to")
    assert scadenze_sdi(SDI) == ["2026-10-31"]          # 15/09 + 46 giorni
    assert scadenze_sdi("Data scadenza 30-11-2026") == ["2026-11-30"]
