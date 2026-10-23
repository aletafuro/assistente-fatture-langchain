"""Cambio Banca d'Italia del GIORNO della fattura, senza rete: la cache viene preparata a mano."""

import json
from decimal import Decimal

import cambi_bdi
import config


def _cache(serie: dict):
    config.CAMBI_BDI.write_text(json.dumps({"USD": serie}), encoding="utf-8")


def _nessuna_rete(monkeypatch):
    def vietato(*a, **k):
        raise AssertionError("il test non deve andare in rete")
    monkeypatch.setattr(cambi_bdi, "_scarica", vietato)


def test_cambio_del_giorno(monkeypatch):
    _nessuna_rete(monkeypatch)
    _cache({"2026-09-17": "1.1481"})
    assert cambi_bdi.quotazione("USD", "2026-09-17") == (Decimal("1.1481"), "2026-09-17")


def test_nel_weekend_usa_il_giorno_precedente(monkeypatch):
    _nessuna_rete(monkeypatch)
    _cache({"2026-09-11": "1.1592"})                # venerdì
    assert cambi_bdi.quotazione("USD", "2026-09-13") == (Decimal("1.1592"), "2026-09-11")   # domenica


def test_cambio_introvabile_non_si_inventa(monkeypatch):
    def rete_giu(*a, **k):
        raise ConnectionError("Banca d'Italia non raggiungibile")
    monkeypatch.setattr(cambi_bdi, "_scarica", rete_giu)
    assert cambi_bdi.quotazione("USD", "2026-09-17") is None


def test_euro_non_si_converte():
    assert cambi_bdi.quotazione("EUR", "2026-09-17") == (Decimal(1), "2026-09-17")


def test_conversione_della_fattura(monkeypatch):
    _nessuna_rete(monkeypatch)
    _cache({"2026-09-17": "1.1481"})
    dati = {"valuta": "USD", "data_emissione": "2026-09-17",
            "imponibile_cent": 100000, "iva_cent": 0, "totale_cent": 100000}
    conv = cambi_bdi.converti_fattura(dati)
    assert conv["cambio_bdi"] == "1.1481"
    assert conv["imponibile_eur_cent"] == 87100      # 1.000 USD / 1,1481 = 871,00 €
    assert conv["totale_eur_cent"] == 87100


def test_totale_in_euro_resta_coerente_al_centesimo(monkeypatch):
    _nessuna_rete(monkeypatch)
    _cache({"2026-09-17": "1.1481"})
    dati = {"valuta": "USD", "data_emissione": "2026-09-17",
            "imponibile_cent": 12345, "iva_cent": 2716, "totale_cent": 15061}
    conv = cambi_bdi.converti_fattura(dati)
    assert conv["imponibile_eur_cent"] + conv["iva_eur_cent"] == conv["totale_eur_cent"]


def test_cambio_scritto_dall_utente(monkeypatch):
    _nessuna_rete(monkeypatch)
    dati = {"valuta": "GBP", "data_emissione": "2026-09-17", "cambio_manuale": "0.8500",
            "imponibile_cent": 8500, "iva_cent": 0, "totale_cent": 8500}
    assert cambi_bdi.converti_fattura(dati)["totale_eur_cent"] == 10000
