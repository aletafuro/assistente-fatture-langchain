"""
DSPy SULL'INTERPRETE DELLE RISPOSTE (lo stesso metodo del notebook del corso, sul nostro problema)
==================================================================================================

Il compito è LOCALE e ha una METRICA, quindi DSPy ha senso (le due domande del corso):
   ingresso: la domanda del bot + la risposta dell'utente
   uscita:   azione (conferma / annulla / valore / assente / altro), campo, valore copiato

Le "regole nascoste" dell'amministrazione (come le convenzioni del team nel corso) stanno negli esempi:
   "nessuna data di scadenza" = il dato NON C'È (assente), non "annulla"  <- errore vero del 13/10
   "non lo so" = altro (il bot richiede), non assente
   "sì ma il numero è 45/B" = correzione (valore), non conferma

Configurazioni confrontate sugli STESSI 24 esempi di misura (gli altri 24 servono solo per ottimizzare):
   A  interprete attuale del bot (LangChain, gpt-4.1-mini, prompt scritto a mano)
   B  DSPy Predict, modello più economico (gpt-4o-mini) (baseline DSPy) + rumore misurato su 3 ripetizioni senza cache
   C  B + LabeledFewShot (16 esempi veri nel prompt)
   D  B + MIPROv2 "light" (riscrive anche l'istruzione; senza esempi, per isolare l'effetto del testo)
Ogni configurazione è una run MLflow (esperimento "interprete-risposte").

Uso:  uv run --group dspy python app/ottimizza_interprete.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal, Optional

os.environ.setdefault("CARTELLA_DATI", str(Path(tempfile.gettempdir()) / "fatture_dspy"))
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import dspy  # noqa: E402
import mlflow  # noqa: E402

import config  # noqa: E402

DATASET = config.BASE / "valutazione" / "risposte_utente.json"
PROGRAMMA = config.BASE / "valutazione" / "interprete_dspy.json"
ESEMPI_PER_IL_BOT = config.BASE / "app" / "interprete_esempi.json"   # finisce nel container (il bot non usa DSPy)
USCITE = ("azione", "campo", "valore")
ETICHETTE = {"fornitore": "il fornitore", "partita_iva": "la partita IVA", "numero": "il numero della fattura",
             "data_emissione": "la data di emissione", "valuta": "la valuta (EUR, USD, GBP...)",
             "paese_fornitore": "il paese del fornitore (es. IT, NL, US)", "totale_cent": "il totale",
             "cambio_manuale": "il cambio Banca d'Italia del giorno della fattura (quantità di valuta per 1 euro)"}
Campo = Literal["fornitore", "paese_fornitore", "indirizzo_fornitore", "partita_iva", "numero", "data_emissione",
                "data_scadenza", "valuta", "imponibile_cent", "iva_cent", "totale_cent", "regime_iva", "cambio_manuale"]


class InterpretaRisposta(dspy.Signature):
    """Interpreta la risposta dell'utente a una domanda del bot che sta registrando una fattura fornitore."""

    domanda: str = dspy.InputField(desc="La domanda fatta dal bot all'utente.")
    campo_atteso: str = dspy.InputField(desc="Il campo che il bot sta chiedendo, oppure 'nessuno'.")
    risposta: str = dspy.InputField(desc="La risposta scritta dall'utente.")
    azione: Literal["conferma", "annulla", "valore", "assente", "altro"] = dspy.OutputField(
        desc="conferma = accetta/approva; annulla = rinuncia alla fattura; valore = fornisce o corregge un dato; "
             "assente = dice che il dato richiesto non c'è sulla fattura; altro = risposta non pertinente.")
    campo: Optional[Campo] = dspy.OutputField(desc="Il campo a cui si riferisce il valore o l'assenza, se c'è.")
    valore: Optional[str] = dspy.OutputField(desc="Il valore COPIATO come l'ha scritto l'utente, senza convertirlo.")


# ---------------------------------------------------------------------------
# DATI E METRICA
# ---------------------------------------------------------------------------
def carica() -> tuple:
    dati = json.loads(DATASET.read_text(encoding="utf-8"))
    domande = dati["domande"]
    esempi = []
    for e in dati["esempi"]:
        testo = domande[e["domanda"]].replace("{etichetta}", ETICHETTE.get(e["campo_atteso"] or "", "il dato"))
        esempi.append(dspy.Example(domanda=testo, campo_atteso=e["campo_atteso"] or "nessuno", risposta=e["risposta"],
                                   azione=e["azione"], campo=e["campo"], valore=e["valore"])
                      .with_inputs("domanda", "campo_atteso", "risposta"))
    return esempi[:24], esempi[24:]


def _norm(v) -> str:
    v = "" if v in (None, "None", "null") else str(v)
    return " ".join(v.lower().strip(" .\"'").split())


def metrica(esempio, predizione, traccia=None) -> float:
    """Credito parziale come nel corso: un terzo di punto per azione, campo e valore.
    Se l'azione non prevede un campo (conferma, annulla, altro), campo e valore contano giusti se vuoti."""
    punti = 0.0
    for uscita in USCITE:
        atteso, ottenuto = _norm(getattr(esempio, uscita)), _norm(getattr(predizione, uscita, None))
        if uscita != "azione" and esempio.azione in ("conferma", "annulla", "altro"):
            ottenuto = ""                          # per queste azioni campo e valore non vengono usati dal bot
        if uscita == "campo" and esempio.azione == "assente" and not ottenuto:
            ottenuto = atteso                      # per "assente" il bot usa il campo che aveva chiesto
        punti += atteso == ottenuto
    return punti / len(USCITE)


def metrica_azione(esempio, predizione, traccia=None) -> float:
    """La cosa più importante per il bot: l'azione (un 'annulla' sbagliato cancella la bozza)."""
    return float(_norm(esempio.azione) == _norm(getattr(predizione, "azione", None)))


# ---------------------------------------------------------------------------
# A: l'interprete attuale del bot, valutato sugli stessi esempi
# ---------------------------------------------------------------------------
class InterpreteAttuale(dspy.Module):
    def forward(self, domanda, campo_atteso, risposta):
        import grafo_bozze
        r = grafo_bozze.interpreta(domanda, risposta, None if campo_atteso == "nessuno" else campo_atteso)
        return dspy.Prediction(azione=r.azione, campo=r.campo, valore=r.valore)


def valuta(programma, misura, metrica_usata=metrica):
    return dspy.Evaluate(devset=misura, metric=metrica_usata, num_threads=8, display_progress=False)(programma)


def registra(nome: str, programma, misura, parametri: dict, extra: dict = None) -> float:
    risultato = valuta(programma, misura)
    azione = valuta(programma, misura, metrica_azione)
    with mlflow.start_run(run_name=nome):
        mlflow.log_params(parametri)
        mlflow.log_metrics({"credito_parziale": risultato.score / 100, "azione_giusta": azione.score / 100} | (extra or {}))
        sbagliati = [{"risposta": e.risposta, "atteso": [e.azione, e.campo, e.valore],
                      "ottenuto": [getattr(p, u, None) for u in USCITE]}
                     for e, p, punti in risultato.results if punti < 1]
        mlflow.log_dict({"sbagliati": sbagliati}, "sbagliati.json")
    print(f"{nome:58s} credito parziale {risultato.score:5.1f}%   azione giusta {azione.score:5.1f}%")
    return risultato.score


def esporta_esempi() -> int:
    """DSPy come "compilatore": gli esempi scelti passano al bot in un file semplice, che l'interprete LangChain
    mette nel suo prompt. Così il container non ha bisogno di DSPy."""
    salvato = json.loads(PROGRAMMA.read_text(encoding="utf-8"))
    esempi = [{k: d.get(k) for k in ("campo_atteso", "risposta", "azione", "campo", "valore")} for d in salvato["demos"]]
    ESEMPI_PER_IL_BOT.write_text(json.dumps(esempi, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(esempi)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--esporta" in sys.argv:
        print(f"esportati {esporta_esempi()} esempi in {ESEMPI_PER_IL_BOT.name}")
        return
    if "--bot" in sys.argv:                 # rimisura l'interprete del bot (LangChain + esempi esportati)
        mlflow.set_tracking_uri(f"sqlite:///{(config.BASE / 'mlflow.db').as_posix()}")
        mlflow.set_experiment("interprete-risposte")
        _, misura = carica()
        registra(f"E  interprete del bot con gli esempi DSPy ({config.MODELLO_INTERPRETE})", InterpreteAttuale(), misura,
                 {"configurazione": "E", "modello": config.MODELLO_INTERPRETE, "tecnica": "LangChain + 16 esempi DSPy"})
        return
    mlflow.set_tracking_uri(f"sqlite:///{(config.BASE / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("interprete-risposte")
    ottimizza, misura = carica()
    # Il corso usava gpt-4.1-nano, nel frattempo ritirato da OpenAI: il modello è un parametro, non è nel codice.
    piccolo = sys.argv[1] if len(sys.argv) > 1 else "gpt-4o-mini"
    dspy.configure(lm=dspy.LM(f"openai/{piccolo}", temperature=0.0, max_tokens=400))
    dspy.configure_cache(enable_disk_cache=True, enable_memory_cache=True)

    registra("A  interprete attuale (gpt-4.1-mini, scritto a mano)", InterpreteAttuale(), misura,
             {"configurazione": "A", "modello": "gpt-4.1-mini", "tecnica": "prompt a mano (LangChain)"})

    baseline = dspy.Predict(InterpretaRisposta)
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)
    ripetizioni = [valuta(baseline, misura).score for _ in range(3)]
    dspy.configure_cache(enable_disk_cache=True, enable_memory_cache=True)
    rumore = max(ripetizioni) - min(ripetizioni)
    print(f"rumore della baseline B (3 ripetizioni senza cache): {rumore:.1f} punti {ripetizioni}")
    base = registra(f"B  DSPy Predict ({piccolo})", baseline, misura,
                    {"configurazione": "B", "modello": piccolo, "tecnica": "Predict"}, {"rumore": rumore / 100})

    pochi = dspy.LabeledFewShot(k=16).compile(dspy.Predict(InterpretaRisposta), trainset=ottimizza)
    c = registra(f"C  + LabeledFewShot, 16 esempi veri ({piccolo})", pochi, misura,
                 {"configurazione": "C", "modello": piccolo, "tecnica": "LabeledFewShot k=16"})

    riscritto = dspy.MIPROv2(metric=metrica, prompt_model=dspy.LM("openai/gpt-4.1-mini", temperature=1.0, max_tokens=3000),
                             auto="light", num_threads=8, seed=42).compile(
        dspy.Predict(InterpretaRisposta), trainset=ottimizza, max_bootstrapped_demos=0, max_labeled_demos=0)
    d = registra(f"D  + MIPROv2 light, istruzione riscritta ({piccolo})", riscritto, misura,
                 {"configurazione": "D", "modello": piccolo, "tecnica": "MIPROv2 light, 0 esempi"})
    print("\nIstruzione scritta da MIPROv2:\n ", riscritto.predictors()[0].signature.instructions)

    migliore, nome = max([(pochi, c), (riscritto, d)], key=lambda x: x[1])
    migliore.save(str(PROGRAMMA))
    esporta_esempi()
    print(f"\nMiglioramento sulla baseline B: {max(c, d) - base:+.1f} punti (rumore {rumore:.1f}). "
          f"Programma migliore salvato in {PROGRAMMA.name}")


if __name__ == "__main__":
    main()
