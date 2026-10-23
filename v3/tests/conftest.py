"""
Preparazione comune dei test.

Regola dei test di questa cartella (come nel modulo MLOps): provano la LOGICA del programma
SENZA chiamare il modello e SENZA rete. Sono veloci, gratuiti e sempre uguali, quindi possono
girare a ogni modifica (anche su GitHub Actions). La qualità del modello si misura a parte,
con il golden set (valutazione/), che costa qualche centesimo e si lancia su richiesta.
"""

import os
import sys
import tempfile
from pathlib import Path

# Prima di importare il codice: cartella dati temporanea, azienda di prova, chiave finta.
_DATI = Path(tempfile.mkdtemp(prefix="fatture_test_"))
os.environ["CARTELLA_DATI"] = str(_DATI)
os.environ["AZIENDA_NOME"] = "Studio Prova S.r.l."
os.environ["AZIENDA_PIVA"] = "IT01234567897"
os.environ.setdefault("OPENAI_API_KEY", "sk-test-non-valida")   # i client si creano, ma nessuno li chiama
os.environ["AVVISI_CANALI"] = ""                                  # nessun avviso vero durante i test

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def registro_vuoto():
    """Ogni test parte con registro, bozze, anagrafica e cache dei cambi vuoti."""
    import config
    for f in (config.REGISTRO, config.BOZZE, config.ANAGRAFICA_ESTERI, config.CAMBI_BDI):
        if f.exists():
            f.unlink()
    yield


@pytest.fixture
def senza_rete(monkeypatch):
    """Verifica P.IVA e cambi senza internet: risposte finte e prevedibili."""
    import anagrafica_esteri
    import verifica_piva

    def verifica_finta(partita_iva, paese):
        return verifica_piva._esito("valida", "VIES", nome_ufficiale(partita_iva), "VIA DI PROVA 1, CITTA")

    monkeypatch.setattr(verifica_piva, "verifica", verifica_finta)
    anagrafica_esteri._verifiche_di_oggi.clear()
    return verifica_finta


def nome_ufficiale(partita_iva):
    return {"NL123456789B01": "NORTHWIND BV"}.get(partita_iva, "FORNITORE PROVA")
