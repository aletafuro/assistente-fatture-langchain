"""Golden set del RAG, misure della ricerca e Langfuse spento senza chiavi (senza modello né rete)."""

import json

import osservabilita
import valuta_rag


def test_golden_set_rag_coerente_con_il_registro_di_prova():
    domande = json.loads(valuta_rag.GOLDEN_SET_RAG.read_text(encoding="utf-8"))["domande"]
    registro = {f["id"]: f for f in json.loads(valuta_rag.REGISTRO_PROVA.read_text(encoding="utf-8"))}
    assert len(domande) >= 15
    for d in domande:
        assert d["domanda"] and d["risposta"]
        for id_fattura in d["fatture"]:                     # ogni fattura attesa esiste e ha l'originale
            assert registro[id_fattura]["percorso_originale"]
    assert any(not d["fatture"] for d in domande)          # almeno una domanda senza risposta nelle fatture


def test_misure_della_ricerca():
    assert valuta_rag.misure_ricerca(["F0003", "F0001", "F0007", "F0009"], ["F0001"]) == \
        {"hit": 1.0, "recall": 1.0, "mrr": 0.5}
    m = valuta_rag.misure_ricerca(["F0005", "F0002", "F0010", "F0004"], ["F0005", "F0010", "F0011"])
    assert m["hit"] == 1.0 and m["mrr"] == 1.0 and round(m["recall"], 2) == 0.67
    assert valuta_rag.misure_ricerca(["F0002"], ["F0001"]) == {"hit": 0.0, "recall": 0.0, "mrr": 0.0}
    assert valuta_rag.misure_ricerca(["F0002"], []) == {}  # domanda senza fatture attese: non si misura


def test_langfuse_spento_senza_chiavi(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert osservabilita.attiva() is False
    assert osservabilita.callbacks() == [] and osservabilita.client() is None
    assert osservabilita.config("prova") == {"callbacks": [], "run_name": "prova"}
