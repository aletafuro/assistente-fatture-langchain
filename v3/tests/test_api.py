"""API REST di sola lettura (api_fatture.py): chiave, ricerca, scadenze, riepilogo, scadenziario.

TestClient chiama l'API come farebbe un programma esterno, ma senza rete e senza avviare il server.
"""

import pytest
from fastapi.testclient import TestClient

import api_fatture
import config
import registro_fatture as reg
import scadenziario

CHIAVE = "chiave-di-prova"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "API_CHIAVE", CHIAVE)
    monkeypatch.setattr(config, "CARTELLA_SCADENZIARIO", tmp_path)
    return TestClient(api_fatture.app, headers={"X-API-Key": CHIAVE})


def _registra(**dati):
    base = {"fornitore": "Rossi S.r.l.", "partita_iva": "01234567897", "numero": "2026/045",
            "data_emissione": "2026-09-10", "data_scadenza": "2026-10-10",
            "imponibile_cent": 10000, "iva_cent": 2200, "totale_cent": 12200, "percorso_originale": "/segreto/f.pdf"}
    return reg.registra_fattura(base | dati)["id"]


# --- la chiave ---------------------------------------------------------------

def test_senza_chiave_niente_dati(client):
    assert client.get("/fatture", headers={"X-API-Key": ""}).status_code == 401
    assert client.get("/fatture", headers={"X-API-Key": "sbagliata"}).status_code == 401


def test_chiave_non_configurata_api_spenta(client, monkeypatch):
    monkeypatch.setattr(config, "API_CHIAVE", None)
    assert client.get("/fatture").status_code == 503
    assert client.get("/salute").json() == {"stato": "ok"}       # il controllo di salute risponde sempre


def test_solo_lettura(client):
    # Nessuna chiamata che scrive: registrare, pagare e annullare restano nella chat.
    assert client.post("/fatture", json={}).status_code == 405
    assert client.delete("/fatture/F0001").status_code == 405


# --- registro ------------------------------------------------------------------

def test_ricerca_come_in_chat_e_campi_interni_nascosti(client):
    _registra()
    _registra(fornitore="Northwind BV", partita_iva="NL123456789B01", numero="INV-7")
    risposta = client.get("/fatture", params={"testo": "rossi 2026/045"}).json()
    assert [f["id"] for f in risposta] == ["F0001"]
    assert risposta[0]["totale_cent"] == 12200 and risposta[0]["data_emissione"] == "2026-09-10"
    assert "percorso_originale" not in risposta[0]                  # i percorsi del server non escono
    assert len(client.get("/fatture").json()) == 2


def test_una_fattura_e_404(client):
    _registra()
    assert client.get("/fatture/f0001").json()["fornitore"] == "Rossi S.r.l."
    assert client.get("/fatture/F0099").status_code == 404


def test_scadenze_con_le_scadute_per_prime(client):
    _registra(numero="1", data_scadenza="2026-10-05")
    _registra(numero="2", data_scadenza="2026-10-20")
    _registra(numero="3", data_scadenza="2027-03-01")                # troppo lontana
    risposta = client.get("/scadenze", params={"entro_giorni": 30, "data_riferimento": "2026-10-10"}).json()
    assert [(s["fattura"]["numero"], s["giorni_alla_scadenza"], s["scaduta"]) for s in risposta] == \
        [("1", -5, True), ("2", 10, False)]


def test_riepilogo_in_centesimi(client):
    _registra(numero="1")
    _registra(numero="2", fornitore="Northwind BV", partita_iva="NL123456789B01",
              imponibile_cent=50000, iva_cent=0, totale_cent=50000, regime_iva="inversione_contabile")
    r = client.get("/riepilogo", params={"tipo": "mese", "anno": 2026, "numero": 9}).json()
    assert r["numero_fatture"] == 2 and r["totale_cent"] == 62200 and r["da_pagare_cent"] == 62200
    assert list(r["per_fornitore_cent"]) == ["Northwind BV", "Rossi S.r.l."]
    assert r["iva_da_verificare"] == ["F0002"]
    assert client.get("/riepilogo", params={"tipo": "anno", "anno": 2026}).json()["numero_fatture"] == 2


def test_riepilogo_parametri_sbagliati(client):
    assert client.get("/riepilogo", params={"tipo": "mese", "anno": 2026}).status_code == 422
    assert client.get("/riepilogo", params={"tipo": "trimestre", "anno": 2026, "numero": 5}).status_code == 422
    assert client.get("/riepilogo", params={"tipo": "settimana", "anno": 2026}).status_code == 422


# --- scadenziario ----------------------------------------------------------------

def test_scadenziario_righe_non_saldate(client):
    fattura = {"fornitore": "Northwind BV", "numero": "INV-0042", "data_emissione": "2026-09-30", "valuta": "EUR",
               "totale_cent": 120000, "tipo_documento": "fattura", "testo": "Bill to Studio Prova IT01234567897"}
    scadenziario.aggiungi(scadenziario.voce_da_fattura(fattura, "scade il 15/11/2026"))
    scadenziario.aggiungi(scadenziario.voce_da_fattura(fattura | {"numero": "INV-0043"}, "scade il 30/12/2026"))
    righe = client.get("/scadenziario").json()
    assert [(r["numero_fattura"], r["data_di_scadenza"], r["importo_euro"]) for r in righe] == \
        [("INV-0042", "2026-11-15", 1200.0), ("INV-0043", "2026-12-30", 1200.0)]
    assert len(client.get("/scadenziario", params={"entro": "2026-11-30"}).json()) == 1
    scadenziario.segna_saldata("Northwind", "INV-0042")
    assert [r["numero_fattura"] for r in client.get("/scadenziario").json()] == ["INV-0043"]
