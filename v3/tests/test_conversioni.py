"""Importi, date e partite IVA: le conversioni che fa Python (l'LLM copia, Python converte).
Ogni caso qui sotto è un errore visto davvero o un formato trovato su una fattura reale."""

import pytest

from fatture_comuni import (PIVA_ESTERO_ASSENTE, euro_in_centesimi, normalizza_data, normalizza_paese,
                            normalizza_piva, normalizza_valuta, piva_italiana_valida)


@pytest.mark.parametrize("testo, centesimi", [
    ("1.200,00", 120000),       # formato italiano
    ("1,200.00", 120000),       # formato inglese (fatture estere)
    ("264,00", 26400),
    ("6.100", 610000),          # errore storico: era letto come 6,10 €
    ("1,500", 150000),          # migliaia all'inglese senza decimali
    ("-16.129,70", -1612970),   # importo negativo (trattenute)
    ("1481.35", 148135),
    ("EUR 1.481,35", 148135),
    ("$ 2,000.50", 200050),
    ("€ 52,504.66", 5250466),
])
def test_importi(testo, centesimi):
    assert euro_in_centesimi(testo) == centesimi


def test_importo_vuoto():
    assert euro_in_centesimi(None) is None


@pytest.mark.parametrize("testo, paese, attesa", [
    ("12/03/2025", None, "2025-03-12"),
    ("2026-09-01", None, "2026-09-01"),
    ("12 marzo 2025", None, "2025-03-12"),
    ("1 September 2026", None, "2026-09-01"),        # inglese, giorno mese anno
    ("September 1, 2026", None, "2026-09-01"),       # inglese, mese giorno anno
    ("01-Sep-2026", None, "2026-09-01"),
    ("1st Sep 2026", None, "2026-09-01"),
    ("3. März 2026", None, "2026-03-03"),            # tedesco
    ("15 juillet 2026", None, "2026-07-15"),         # francese
    ("1 mei 2026", None, "2026-05-01"),              # olandese
    ("9/17/2026", "US", "2026-09-17"),               # americana: mese/giorno/anno
    ("09/01/2026", "US", "2026-09-01"),
    ("09/01/2026", "NL", "2026-01-09"),              # europea: giorno/mese/anno
])
def test_date(testo, paese, attesa):
    assert normalizza_data(testo, paese) == attesa


def test_data_sconosciuta_resta_vuota():
    # Meglio vuoto (e il bot la chiede) che sbagliato.
    assert normalizza_data("presto", None) is None


@pytest.mark.parametrize("testo, paese, attesa", [
    ("IT 01234567890", None, ("01234567890", "IT")),
    ("01234567890", None, ("01234567890", "IT")),
    ("NL.123.456.789.B.01", None, ("NL123456789B01", "NL")),
    ("VAT REG: NL.123456789.B.01", None, ("NL123456789B01", "NL")),
    ("1234567T", "IE", ("IE1234567T", "IE")),
    ("EL123456789", "GR", ("EL123456789", "EL")),     # la Grecia nel VIES è EL
    ("GB123456789", None, ("GB123456789", "GB")),
    ("EIN 12-3456789", "US", ("US123456789", "US")),
    ("EU372000041", "US", ("EU372000041", "US")),     # numero OSS di un fornitore extra-UE
])
def test_partite_iva(testo, paese, attesa):
    assert normalizza_piva(testo, paese) == attesa


def test_estero_senza_partita_iva_usa_il_codice_convenzionale():
    assert normalizza_piva("", "US") == (PIVA_ESTERO_ASSENTE, "US")
    assert normalizza_piva(None, "NL") == (PIVA_ESTERO_ASSENTE, "NL")
    assert PIVA_ESTERO_ASSENTE == "OO" + "9" * 11


def test_italiana_senza_partita_iva_resta_da_chiedere():
    assert normalizza_piva("", None) == (None, None)


def test_la_nostra_partita_iva_non_e_mai_del_fornitore():
    # Sulle fatture estere c'è spesso anche la partita IVA del cliente (noi): va scartata.
    assert normalizza_piva("IT01234567897", "LT") == (PIVA_ESTERO_ASSENTE, "LT")


@pytest.mark.parametrize("piva, valida", [("01234567897", True), ("01234567890", False), ("123", False)])
def test_cifra_di_controllo_italiana(piva, valida):
    assert piva_italiana_valida(piva) is valida


def test_paesi_e_valute():
    assert normalizza_paese("gr") == "EL"
    assert normalizza_paese("UK") == "GB"
    assert normalizza_paese("Italia") is None
    assert normalizza_valuta("$") == "USD"
    assert normalizza_valuta("€") == "EUR"
    assert normalizza_valuta("usd") == "USD"


def test_trattino_codificato_come_carattere_nullo():
    # Visto sulle fatture generate da Stripe: il trattino arriva come \x00.
    from fatture_comuni import pulisci_testo_pdf
    assert pulisci_testo_pdf("Invoice number 9BF0758D\x005703622\nDate") == "Invoice number 9BF0758D-5703622\nDate"
    assert pulisci_testo_pdf("IN\x0079313654") == "IN-79313654"
    assert pulisci_testo_pdf("fine\x00") == "fine"


def test_data_a_parole_di_un_fornitore_americano():
    # Errore trovato sulle fatture vere: la regola mese/giorno veniva applicata anche alle date a parole.
    assert normalizza_data("21 settembre 2026", "US") == "2026-09-21"
    assert normalizza_data("September 21, 2026", "US") == "2026-09-21"


def test_data_americana_riconosciuta_anche_senza_paese():
    assert normalizza_data("09/30/2026", "GB") == "2026-09-30"     # il 30 non può essere un mese
    assert normalizza_data("09/10/2026", "GB") == "2026-10-09"     # ambigua: resta giorno/mese


def test_codice_vecchio_della_corona_ceca():
    assert normalizza_valuta("CSK") == "CZK"


def test_numero_con_la_data_attaccata():
    from fatture_comuni import pulisci_numero
    assert pulisci_numero("1 - 09/08/2026") == "1"
    assert pulisci_numero("2026-0089") == "2026-0089"


def test_se_una_data_e_americana_lo_sono_tutte():
    # Fattura vera: emissione "09/30/2026", scadenza "10/07/2026" (7 ottobre, non 10 luglio).
    from fatture_comuni import DatiFattura, in_dizionario
    d = in_dizionario("f.pdf", DatiFattura(fornitore="Rossi Ltd", paese_fornitore="GB", data_emissione="09/30/2026",
                                           data_scadenza="10/07/2026", regime_iva="esente"))
    assert d["data_emissione"] == "2026-09-30" and d["data_scadenza"] == "2026-10-07"


def test_la_risposta_salvata_del_modello_si_riusa_senza_richiamarlo(monkeypatch):
    import estrazione
    from fatture_comuni import DatiFattura
    grezzo = DatiFattura(fornitore="Rossi S.r.l.", numero="7", data_emissione="1 September 2026",
                         totale="1,200.00", regime_iva="ordinario").model_dump()

    def vietato(*a, **k):
        raise AssertionError("non deve chiamare il modello")
    monkeypatch.setattr(estrazione, "_chain_testo", type("C", (), {"invoke": vietato})())
    d = estrazione.estrai_da_testo("testo qualsiasi", "f.pdf", grezzo=grezzo)
    assert d["data_emissione"] == "2026-09-01" and d["totale_cent"] == 120000


@pytest.mark.parametrize("testo, centesimi", [("0%", 0), ("99.00 USD", 9900), ("46.887,00 Kč", 4688700), ("n/d", None)])
def test_importi_scritti_in_modo_strano(testo, centesimi):
    # Visto su una ricevuta: l'IVA "0%" faceva fallire la conversione (e sembrava un guasto di OpenAI).
    assert euro_in_centesimi(testo) == centesimi
