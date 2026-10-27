"""Indice del RAG (rag_fatture.py), in memoria e su pgvector, con embedding FINTI: niente modello, niente costi.

Il test su pgvector gira solo se c'è un Postgres con pgvector (PGVECTOR_TEST_URL, o PGVECTOR_URL del .env):
su GitHub Actions lo avvia il workflow come servizio, sul PC il container pgvector-fatture.
"""

import json
import os
import uuid

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import config
import percorsi_v2
import rag_fatture
import registro_fatture as reg


def _fattura(id_fattura, testo, cartella, annullata=False):
    originale = cartella / f"{id_fattura}.txt"
    originale.write_text(testo, encoding="utf-8")
    return {"id": id_fattura, "fornitore": f"Fornitore {id_fattura}", "numero": id_fattura[-2:],
            "data_emissione": "2026-09-01", "percorso_originale": str(originale), "annullata": annullata}


@pytest.fixture
def indice(monkeypatch, tmp_path, request):
    monkeypatch.setattr(rag_fatture, "OpenAIEmbeddings", lambda model: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(percorsi_v2, "RAG_TESTI", tmp_path / "testi.json")
    monkeypatch.setattr(rag_fatture, "_indice", None)
    tipo = request.param
    if tipo == "pgvector":
        url = os.getenv("PGVECTOR_TEST_URL") or os.getenv("PGVECTOR_URL")
        if not url:
            pytest.skip("nessun Postgres con pgvector configurato")
        monkeypatch.setattr(config, "PGVECTOR_URL", url)
        monkeypatch.setattr(config, "RAG_COLLEZIONE", f"test_{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(config, "RAG_INDICE", tipo)
    fatture = [_fattura("F0001", "Toner compatibili e carta A4", tmp_path),
               _fattura("F0002", "Trasporto merci giugno", tmp_path),
               _fattura("F0003", "Catering evento aziendale", tmp_path, annullata=True)]
    monkeypatch.setattr(reg, "carica_registro", lambda: fatture)
    yield fatture, tmp_path
    rag_fatture.svuota_indice()


@pytest.mark.parametrize("indice", ["memoria", "pgvector"], indirect=True)
def test_indice_con_gli_id_delle_fatture_e_senza_annullate(indice):
    fatture, cartella = indice
    trovate = rag_fatture.cerca("qualsiasi cosa", k=10)
    assert sorted(d.metadata["id"] for d in trovate) == ["F0001", "F0002"]          # la F0003 è annullata
    assert json.loads(percorsi_v2.RAG_TESTI.read_text(encoding="utf-8"))["F0001"].startswith("Toner")

    # Una fattura nuova entra una volta sola, anche se si aggiunge due volte.
    nuova = _fattura("F0004", "Licenze software", cartella)
    fatture.append(nuova)
    rag_fatture.aggiungi(nuova)
    rag_fatture.aggiungi(nuova)
    assert sorted(d.metadata["id"] for d in rag_fatture.cerca("x", k=10)) == ["F0001", "F0002", "F0004"]


@pytest.mark.parametrize("indice", ["pgvector"], indirect=True)
def test_pgvector_resta_salvato_e_ricalcola_solo_i_nuovi(indice, monkeypatch):
    fatture, cartella = indice
    rag_fatture.cerca("x")                                               # primo avvio: indice creato
    monkeypatch.setattr(rag_fatture, "_indice", None)                    # "riavvio" del bot
    fatture[2]["annullata"] = False
    fatture[0]["annullata"] = True
    aggiunti = []
    originale = rag_fatture._nuovo_indice

    def conta():
        store = originale()
        add = store.add_documents
        store.add_documents = lambda docs, ids: (aggiunti.extend(ids), add(docs, ids=ids))[1]
        return store
    monkeypatch.setattr(rag_fatture, "_nuovo_indice", conta)
    assert sorted(d.metadata["id"] for d in rag_fatture.cerca("x", k=10)) == ["F0002", "F0003"]
    assert aggiunti == [rag_fatture._chiave("F0003")]                     # embedding calcolati solo per la fattura che mancava
