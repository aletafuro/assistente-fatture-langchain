"""Controlli della bozza, registro, duplicati, ricerca e anagrafica dei fornitori esteri (senza LLM né rete)."""

import json

import anagrafica_esteri
import bozze_fatture as boz
import cambi_bdi
import config
import registro_fatture as reg
from fatture_comuni import PIVA_ESTERO_ASSENTE


def _bozza(**dati):
    base = {"fornitore": "Rossi S.r.l.", "paese_fornitore": "IT", "partita_iva": "01234567897", "numero": "45",
            "data_emissione": "2026-09-10", "data_scadenza": "2026-10-10", "valuta": "EUR",
            "imponibile_cent": 10000, "iva_cent": 2200, "totale_cent": 12200, "regime_iva": "ordinario"}
    b = {"dati": base | dati}
    boz._aggiorna_controlli(b)
    return b


# --- controlli della bozza -------------------------------------------------

def test_fattura_italiana_completa():
    b = _bozza()
    assert b["mancanti"] == [] and b["avvisi"] == []


def test_partita_iva_italiana_sbagliata_viene_segnalata():
    assert any("non valida" in a for a in _bozza(partita_iva="01234567890")["avvisi"])


def test_estero_senza_partita_iva(senza_rete):
    b = _bozza(fornitore="Northwind Inc", paese_fornitore="US", partita_iva=None)
    assert b["dati"]["partita_iva"] == PIVA_ESTERO_ASSENTE
    assert "partita_iva" not in b["mancanti"]


def test_reverse_charge_senza_iva_scritta_vale_zero(senza_rete):
    b = _bozza(fornitore="Northwind BV", paese_fornitore="NL", partita_iva="NL123456789B01",
               regime_iva="inversione_contabile", iva_cent=None, totale_cent=10000)
    assert b["dati"]["iva_cent"] == 0 and "iva_cent" not in b["mancanti"]


def test_nessuna_scadenza_usa_la_data_della_fattura():
    b = _bozza(data_scadenza=None, scadenza_assente=True)
    assert b["dati"]["data_scadenza"] == "2026-09-10"


def test_cambio_mancante_viene_chiesto(monkeypatch, senza_rete):
    monkeypatch.setattr(cambi_bdi, "quotazione", lambda valuta, giorno: None)
    b = _bozza(fornitore="Northwind Inc", paese_fornitore="US", partita_iva=None, valuta="USD")
    assert "cambio_manuale" in b["mancanti"]


def test_fees_a_parte_danno_un_avviso():
    b = _bozza(iva_cent=0, imponibile_cent=4662, totale_cent=4696)
    assert any("incoerenti" in a for a in b["avvisi"])


# --- registro --------------------------------------------------------------

def test_registro_salva_euro_e_valuta(monkeypatch, senza_rete):
    monkeypatch.setattr(cambi_bdi, "quotazione", lambda v, g: (__import__("decimal").Decimal("1.1481"), g))
    b = _bozza(fornitore="Northwind Inc", paese_fornitore="US", partita_iva=None, valuta="USD",
               imponibile_cent=100000, iva_cent=0, totale_cent=100000, regime_iva="esente")
    esito = reg.registra_fattura(b["dati"])
    f = reg.trova_fattura(esito["id"])
    assert f["totale_cent"] == 87100                 # nel registro: euro
    assert f["totale_valuta_cent"] == 100000         # originale in dollari
    assert f["valuta"] == "USD" and f["cambio_bdi"] == "1.1481"


def test_duplicato_bloccato():
    reg.registra_fattura(_bozza()["dati"])
    assert reg.registra_fattura(_bozza()["dati"])["esito"] == "duplicato"


def test_due_esteri_senza_partita_iva_non_sono_lo_stesso_fornitore(senza_rete):
    # OO99999999999 è uguale per tutti: il duplicato si riconosce dal nome.
    reg.registra_fattura(_bozza(fornitore="Northwind Inc", paese_fornitore="US", partita_iva=None, numero="1")["dati"])
    altro = reg.registra_fattura(_bozza(fornitore="Contoso LLC", paese_fornitore="US", partita_iva=None, numero="1")["dati"])
    assert altro["esito"] == "registrata"


def test_ricerca_per_parole_e_per_codice():
    reg.registra_fattura(_bozza(fornitore="Rossi S.p.A.", numero="2026/045")["dati"])
    assert "F0001" in reg.cerca_fatture("rossi 2026/045")       # nome e numero insieme
    assert "F0001" in reg.cerca_fatture("F0001")                # codice del registro
    assert reg.cerca_fatture("bianchi") == "Nessuna fattura trovata."


# --- anagrafica fornitori esteri ------------------------------------------

def _registrata(**dati):
    esito = reg.registra_fattura(_bozza(**dati)["dati"])
    return reg.trova_fattura(esito["id"])


def test_prima_fattura_crea_la_scheda(senza_rete):
    f = _registrata(fornitore="Northwind BV", paese_fornitore="NL", partita_iva="NL123456789B01",
                    regime_iva="inversione_contabile", iva_cent=0, totale_cent=10000)
    avvisi = anagrafica_esteri.aggiorna_da_fattura(f)
    assert "Creata la scheda" in avvisi[0]
    assert anagrafica_esteri.carica()[0]["ufficiale"]["nome_ufficiale"] == "NORTHWIND BV"


def test_fattura_italiana_non_entra_in_anagrafica():
    assert anagrafica_esteri.aggiorna_da_fattura(_registrata()) == []


def test_nome_cambiato_finisce_nello_storico(senza_rete):
    estero = dict(paese_fornitore="NL", partita_iva="NL123456789B01", regime_iva="inversione_contabile",
                  iva_cent=0, totale_cent=10000)
    anagrafica_esteri.aggiorna_da_fattura(_registrata(fornitore="Northwind BV", numero="1", **estero))
    avvisi = anagrafica_esteri.aggiorna_da_fattura(_registrata(fornitore="Northwind Europe BV", numero="2", **estero))
    assert "nome cambiato" in avvisi[0]
    assert anagrafica_esteri.carica()[0]["storico"][0]["dopo"] == "Northwind Europe BV"


def test_controllo_mensile_trova_l_indirizzo_cambiato(monkeypatch, senza_rete):
    estero = dict(paese_fornitore="NL", partita_iva="NL123456789B01", regime_iva="inversione_contabile",
                  iva_cent=0, totale_cent=10000)
    anagrafica_esteri.aggiorna_da_fattura(_registrata(fornitore="Northwind BV", **estero))
    import verifica_piva
    monkeypatch.setattr(verifica_piva, "verifica", lambda p, paese: verifica_piva._esito(
        "valida", "VIES", "NORTHWIND BV", "NUOVA STRADA 9, AMSTERDAM"))
    testo = anagrafica_esteri.controllo_mensile()
    assert "indirizzo ufficiale cambiato" in testo


def test_vies_occupato_non_vuol_dire_non_valida(monkeypatch):
    import verifica_piva

    class Risposta:
        def raise_for_status(self): pass
        def json(self): return {"isValid": False, "userError": "MS_MAX_CONCURRENT_REQ"}

    monkeypatch.setattr(verifica_piva.httpx, "get", lambda *a, **k: Risposta())
    monkeypatch.setattr(verifica_piva.time, "sleep", lambda s: None)
    assert verifica_piva.verifica("NL123456789B01", "NL")["esito"] == "non_disponibile"


def _fattura_estera(**dati):
    base = {"id": "f.pdf", "fornitore": "Spire Media Limited", "partita_iva": "HK12345678", "paese_fornitore": "HK",
            "indirizzo_fornitore": "18 Luard Rd, Wan Chai", "numero": "AS-001", "data_emissione": "2026-09-30"}
    return base | dati


def test_rielaborare_la_stessa_fattura_non_crea_modifiche(senza_rete):
    # Caso vero: la stessa fattura elaborata più volte, letta una volta HK e una volta IE.
    anagrafica_esteri.aggiorna_da_fattura(_fattura_estera())
    assert anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="IE12345678", paese_fornitore="IE")) == []
    scheda = anagrafica_esteri.carica()[0]
    assert scheda["storico"] == [] and len(scheda["fatture"]) == 1


def test_cambia_solo_il_prefisso_del_paese_non_e_un_cambio_di_partita_iva(senza_rete):
    anagrafica_esteri.aggiorna_da_fattura(_fattura_estera())
    avvisi = anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="IE12345678", paese_fornitore="IE",
                                                                   numero="AS-002", data_emissione="2026-10-31"))
    assert "paese della partita IVA da controllare" in avvisi[0]
    assert anagrafica_esteri.carica()[0]["storico"] == []


def test_partita_iva_davvero_cambiata(senza_rete):
    anagrafica_esteri.aggiorna_da_fattura(_fattura_estera())
    avvisi = anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="HK99999999", numero="AS-002",
                                                                   data_emissione="2026-10-31"))
    assert "partita IVA cambiato" in avvisi[0]


def test_stesso_indirizzo_scritto_in_modo_diverso():
    from anagrafica_esteri import _uguale
    assert _uguale("Calle Mayor 10, Planta 2, 29001 Málaga, Spain",
                   "Calle Mayor 10 Planta 2 29001 Málaga Málaga Spain", indirizzo=True)      # caso vero (Lucerne Stock)
    assert _uguale("WOODGROVE N.V.", "Woodgrove NV")
    assert not _uguale("Calle Mayor 10, Málaga", "Calle Larios 5, Málaga")      # via diversa: cambiato


def test_partita_iva_non_letta_non_e_un_cambio(senza_rete):
    # Caso vero (NWD): "Tin Number: 10000001X" letto una volta sì e una volta no.
    anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="CY10000001X", paese_fornitore="CY"))
    avvisi = anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="OO99999999999", paese_fornitore="CY",
                                                                   numero="AS-002", data_emissione="2026-10-31"))
    assert "non trovata sulla fattura" in avvisi[0] and anagrafica_esteri.carica()[0]["storico"] == []


def test_numero_oss_accanto_alla_partita_iva_non_e_un_cambio(senza_rete):
    # Caso vero (Litware): fattura e nota di credito riportano sia "GB 123456782" sia "EU372000025".
    anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="GB123456782", paese_fornitore="GB"))
    avvisi = anagrafica_esteri.aggiorna_da_fattura(_fattura_estera(partita_iva="EU372000025", paese_fornitore="GB",
                                                                   numero="CN-1", data_emissione="2026-09-30"))
    assert "da controllare quale usare" in avvisi[0] and anagrafica_esteri.carica()[0]["storico"] == []


def test_paese_in_fondo_all_indirizzo_non_e_un_cambio():
    from anagrafica_esteri import _uguale
    assert _uguale("2 Queens Ave Oakleigh VIC 3166 Australia", "2 Queens Ave Oakleigh VIC  3166", indirizzo=True)
    assert not _uguale("Northwind BV", "Northwind Europe BV")       # nel NOME una parola in più è un cambio vero
