"""
VALUTAZIONE DEL RAG SUL CONTENUTO DELLE FATTURE (RAGAS + MLflow, e Langfuse se configurato)
===========================================================================================

Domanda: quando il bot cerca "chi ci ha venduto il toner?", trova le fatture giuste? E la risposta
dice solo cose scritte nelle fatture, o inventa?

Golden set: valutazione/golden_set_rag.json (16 domande, risposta giusta e fatture dove si trova).
Corpus: le fatture inventate di valutazione/registro_esempio_rag.json, con gli originali in file_di_prova/.

Due livelli di misura:
  1. RICERCA, in Python, gratis e sempre uguale: la fattura giusta è tra le prime K? (hit, recall, MRR)
  2. RISPOSTA, con RAGAS (un LLM fa da giudice, costa qualche centesimo):
       context_precision  le fatture utili sono in cima ai risultati?
       context_recall     nei risultati c'è tutto quello che serve per la risposta giusta?
       faithfulness       ogni affermazione della risposta è scritta nelle fatture trovate? (niente invenzioni)
       factual_correctness la risposta dice le stesse cose della risposta giusta?
       answer_relevancy   la risposta risponde proprio alla domanda?

La ricerca è quella VERA del bot (rag_fatture.cerca, la stessa del tool dell'agente). La risposta la
scrive lo stesso modello dell'agente con le sole fatture trovate: così si misura il RAG da solo, senza
il resto dell'agente (che per una domanda su un totale userebbe il registro, non il RAG).

Uso (dalla cartella v3):
    uv run --group dev --group valutazione python app/valuta_rag.py                    # indice in memoria
    uv run --group dev --group valutazione python app/valuta_rag.py --indice pgvector  # Postgres + pgvector
Scrive valutazione/risultati_rag_<indice>.json e valutazione/VALUTAZIONE_RAG_<indice>.md, una run MLflow ("rag-fatture")
e, se Langfuse è configurato, una traccia per domanda con i punteggi.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path

VALUTAZIONE = Path(__file__).resolve().parent.parent / "valutazione"
GOLDEN_SET_RAG = VALUTAZIONE / "golden_set_rag.json"
REGISTRO_PROVA = VALUTAZIONE / "registro_esempio_rag.json"
# Testi già estratti dagli originali (foto e vocale passano da un modello): si salvano per non
# ripagarli a ogni giro e perché il confronto tra versioni parta dagli stessi testi.
TESTI_PROVA = VALUTAZIONE / "rag_testi_esempio.json"
MODELLO_RISPOSTA = "gpt-4.1-mini"        # lo stesso dell'agente (agente_v2.py)
MODELLO_GIUDICE = "gpt-4.1-mini"

ISTRUZIONI = ("Rispondi alla domanda sulle fatture fornitori usando SOLO i brani qui sotto, che sono il "
              "risultato della ricerca nel testo delle fatture. Cita fornitore e numero di fattura. "
              "Se la risposta non è nei brani, dillo chiaramente: non inventare.")


def _prepara_dati(indice: str) -> Path:
    """Registro di prova in una cartella temporanea, PRIMA di importare il codice: quello vero non si tocca."""
    if "config" in sys.modules:
        raise RuntimeError("valuta_rag va lanciato da solo (python app/valuta_rag.py), non importato.")
    dati = Path(tempfile.mkdtemp(prefix="valuta_rag_"))
    os.environ["CARTELLA_DATI"] = str(dati)
    os.environ["RAG_INDICE"] = indice
    os.environ["RAG_COLLEZIONE"] = "fatture_valutazione"     # mai la collezione delle fatture vere
    import percorsi_v2
    shutil.copy(REGISTRO_PROVA, dati / "registro.json")
    if TESTI_PROVA.exists():
        shutil.copy(TESTI_PROVA, percorsi_v2.RAG_TESTI)
    return dati


def _id(documento) -> str:
    return documento.metadata["id"]


def misure_ricerca(trovate: list, attese: list) -> dict:
    """Hit (almeno una giusta tra le prime K), recall (quante delle giuste), MRR (1 / posizione della prima)."""
    if not attese:
        return {}
    posizioni = [i for i, f in enumerate(trovate, start=1) if f in attese]
    return {"hit": 1.0 if posizioni else 0.0,
            "recall": len(set(trovate) & set(attese)) / len(attese),
            "mrr": 1 / posizioni[0] if posizioni else 0.0}


def _ragas():
    # ragas 0.3.1 (l'ultima compatibile con openai 3.x) importa un modulo Vertex AI che langchain-community
    # 0.4 non ha più: non lo usiamo, basta un modulo vuoto al suo posto.
    for nome in ("langchain_community.chat_models.vertexai", "langchain_community.llms.vertexai"):
        modulo = types.ModuleType(nome)
        modulo.ChatVertexAI = modulo.VertexAI = type("NonUsato", (), {})
        sys.modules.setdefault(nome, modulo)
    import ragas
    return ragas


def valuta() -> dict:
    import osservabilita
    import rag_fatture
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

    rag_fatture.svuota_indice()                 # con pgvector: si riparte da zero a ogni valutazione
    domande = json.loads(GOLDEN_SET_RAG.read_text(encoding="utf-8"))["domande"]
    modello = init_chat_model(f"openai:{MODELLO_RISPOSTA}", temperature=0)
    langfuse = osservabilita.client()

    righe = []
    inizio = time.time()
    for d in domande:
        def rispondi():
            trovati = rag_fatture.cerca(d["domanda"])
            brani = [t.page_content for t in trovati]
            risposta = modello.invoke(
                [SystemMessage(ISTRUZIONI), HumanMessage(d["domanda"] + "\n\nBRANI:\n\n" + "\n\n---\n\n".join(brani))],
                config=osservabilita.config("risposta-rag")).content
            return trovati, brani, risposta

        if langfuse:
            # Una traccia per domanda: dentro si vedono la ricerca e la chiamata al modello.
            with langfuse.start_as_current_observation(as_type="span", name="valutazione-rag",
                                                       input={"domanda": d["domanda"]}) as span:
                trovati, brani, risposta = rispondi()
                span.update(output=risposta, metadata={"fatture_trovate": [_id(t) for t in trovati]})
                id_traccia = langfuse.get_current_trace_id()
        else:
            (trovati, brani, risposta), id_traccia = rispondi(), None
        ids = [_id(t) for t in trovati]
        righe.append({"domanda": d["domanda"], "riferimento": d["risposta"], "attese": d["fatture"],
                      "trovate": ids, "brani": brani, "risposta": risposta, "traccia": id_traccia,
                      "ricerca": misure_ricerca(ids, d["fatture"])})
    shutil.copy(__import__("percorsi_v2").RAG_TESTI, TESTI_PROVA)     # testi pronti per il prossimo giro

    # --- RAGAS: un LLM giudica ogni risposta --------------------------------------------------------
    ragas = _ragas()
    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (FactualCorrectness, Faithfulness, LLMContextPrecisionWithReference,
                               LLMContextRecall, ResponseRelevancy)
    giudice = LangchainLLMWrapper(init_chat_model(f"openai:{MODELLO_GIUDICE}", temperature=0))
    metriche = [LLMContextPrecisionWithReference(), LLMContextRecall(), Faithfulness(),
                FactualCorrectness(), ResponseRelevancy()]
    campioni = ragas.EvaluationDataset([ragas.SingleTurnSample(
        user_input=r["domanda"], retrieved_contexts=r["brani"], response=r["risposta"], reference=r["riferimento"])
        for r in righe])
    esito = ragas.evaluate(campioni, metrics=metriche, llm=giudice,
                           embeddings=LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small")),
                           show_progress=False)
    tabella = esito.to_pandas()
    nomi = [m.name for m in metriche]
    # Alcune colonne hanno i parametri nel nome, es. "factual_correctness(mode=f1)".
    colonne = {n: next(c for c in tabella.columns if c == n or c.startswith(n + "(")) for n in nomi}
    for r, (_, punteggi) in zip(righe, tabella.iterrows()):
        r["ragas"] = {n: (None if punteggi[c] != punteggi[c] else round(float(punteggi[c]), 3))
                      for n, c in colonne.items()}

    # --- medie ------------------------------------------------------------------------------------
    def media(valori):
        valori = [v for v in valori if v is not None]
        return round(sum(valori) / len(valori), 3) if valori else None
    con_attese = [r for r in righe if r["ricerca"]]
    riassunto = {
        "data": datetime.now().isoformat(timespec="seconds"), "indice": type(rag_fatture._indice).__name__,
        "k": rag_fatture.K, "modello_risposta": MODELLO_RISPOSTA, "modello_giudice": MODELLO_GIUDICE,
        "domande": len(righe), "secondi": round(time.time() - inizio),
        "ricerca": {m: media([r["ricerca"][m] for r in con_attese]) for m in ("hit", "recall", "mrr")},
        "ragas": {n: media([r["ragas"][n] for r in righe]) for n in nomi},
    }
    if langfuse:
        for r in righe:
            for n, v in r["ragas"].items():
                if v is not None:
                    langfuse.create_score(name=n, value=v, trace_id=r["traccia"])
        langfuse.flush()
    return {"riassunto": riassunto, "domande": righe}


def salva(risultati: dict) -> None:
    # Un file per indice (memoria / pgvector): il confronto prima/dopo resta nel repository.
    nome = os.environ["RAG_INDICE"]
    (VALUTAZIONE / f"risultati_rag_{nome}.json").write_text(json.dumps(risultati, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    r = risultati["riassunto"]
    nomi = list(r["ragas"])
    md = [f"# Valutazione del RAG ({r['data'][:10]})", "",
          f"Indice: `{r['indice']}` · K = {r['k']} · risposta: {r['modello_risposta']} · giudice RAGAS: "
          f"{r['modello_giudice']} · {r['domande']} domande", "",
          "| Ricerca: hit@K | recall@K | MRR | " + " | ".join(nomi) + " |",
          "|---" * (3 + len(nomi)) + "|",
          f"| {r['ricerca']['hit']} | {r['ricerca']['recall']} | {r['ricerca']['mrr']} | "
          + " | ".join(str(r["ragas"][n]) for n in nomi) + " |", "",
          "| Domanda | Attese | Trovate | " + " | ".join(nomi) + " |", "|---" * (3 + len(nomi)) + "|"]
    for d in risultati["domande"]:
        md.append(f"| {d['domanda']} | {', '.join(d['attese']) or '—'} | {', '.join(d['trovate'])} | "
                  + " | ".join("—" if d["ragas"][n] is None else str(d["ragas"][n]) for n in nomi) + " |")
    (VALUTAZIONE / f"VALUTAZIONE_RAG_{nome}.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def registra_in_mlflow(risultati: dict) -> None:
    import config
    import mlflow
    r = risultati["riassunto"]
    mlflow.set_tracking_uri(f"sqlite:///{(config.BASE / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("rag-fatture")
    with mlflow.start_run(run_name=f"{r['indice']} · k={r['k']}"):
        mlflow.log_params({k: r[k] for k in ("indice", "k", "modello_risposta", "modello_giudice", "domande")})
        mlflow.log_metrics({f"ricerca_{k}": v for k, v in r["ricerca"].items()}
                           | {k: v for k, v in r["ragas"].items() if v is not None})
        mlflow.log_artifact(str(VALUTAZIONE / f"VALUTAZIONE_RAG_{os.environ['RAG_INDICE']}.md"))


if __name__ == "__main__":
    import argparse
    argomenti = argparse.ArgumentParser(description="Valutazione del RAG con RAGAS")
    argomenti.add_argument("--indice", choices=["memoria", "pgvector"], default="memoria",
                           help="pgvector: serve PGVECTOR_URL nel .env (vedi README)")
    cartella = _prepara_dati(argomenti.parse_args().indice)
    risultati = valuta()
    salva(risultati)
    registra_in_mlflow(risultati)
    print(json.dumps(risultati["riassunto"], ensure_ascii=False, indent=2))
    shutil.rmtree(cartella, ignore_errors=True)
