"""
ESPERIMENTI CON MLFLOW: quale modello legge meglio le fatture, e a che costo?
============================================================================

Un "esperimento" = una prova registrata (run) con:
   - PARAMETRI  : cosa abbiamo scelto (modello per il testo, modello per le foto, versione delle istruzioni, giri)
   - METRICHE   : cosa è venuto fuori (accuratezza sulle italiane e sulle estere, rumore, token, costo, durata)
   - ARTEFATTI  : il dettaglio di ogni fattura (JSON), per capire DOVE sbaglia

Le run finiscono in mlflow.db (nella cartella v3, fuori dal repository) e si confrontano con:
   uv run mlflow ui --backend-store-uri sqlite:///mlflow.db        ->  http://localhost:5000

Uso:
   uv run python app/esperimento.py                       # modelli della configurazione
   uv run python app/esperimento.py gpt-4.1-mini          # stessa prova con un altro modello per il testo
   uv run python app/esperimento.py gpt-4o-mini 3         # ... e 3 giri sul golden set italiano

Il modello si sceglie PRIMA di importare il codice (è letto dalla configurazione all'avvio).
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

if len(sys.argv) > 1:
    os.environ["MODELLO_LETTURA_TESTO"] = sys.argv[1]
GIRI = int(sys.argv[2]) if len(sys.argv) > 2 else 3
# Ogni modello ha la sua cartella dati (e le sue letture salvate): non si mescolano letture di modelli diversi.
# Va impostata PRIMA di importare config, che la legge all'avvio.
os.environ["CARTELLA_DATI"] = str(Path(tempfile.gettempdir()) / "fatture_esperimenti" /
                                  os.environ.get("MODELLO_LETTURA_TESTO", "gpt-4.1-mini"))

import mlflow  # noqa: E402
from langchain_community.callbacks import get_openai_callback  # noqa: E402

import config  # noqa: E402
import fatture_comuni  # noqa: E402
import valuta_estere  # noqa: E402
import valuta_golden_set  # noqa: E402

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mlflow.set_tracking_uri(f"sqlite:///{(config.BASE / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("lettura-fatture")
    versione_istruzioni = hashlib.sha256(fatture_comuni.ISTRUZIONI_ESTRAZIONE.encode()).hexdigest()[:8]

    with mlflow.start_run(run_name=f"{config.MODELLO_TESTO} · istruzioni {versione_istruzioni}"):
        mlflow.log_params({"modello_testo": config.MODELLO_TESTO, "modello_foto": config.MODELLO_FOTO,
                           "versione_istruzioni": versione_istruzioni, "giri_italiane": GIRI,
                           "temperature": 0})
        mlflow.log_text(fatture_comuni.ISTRUZIONI_ESTRAZIONE, "istruzioni.txt")
        with get_openai_callback() as consumo:
            italiane = valuta_golden_set.valuta(GIRI, rapporto=False)
            estere = valuta_estere.valuta()
        mlflow.log_metrics({
            "italiane_accuratezza": italiane["accuratezza"],
            "italiane_rumore": italiane["rumore"],
            "estere_tutto_giusto": estere["corrette"] / estere["fatture"],
            "estere_lettura": estere["accuratezza_lettura"],
            "estere_euro": estere["accuratezza_euro"],
            "token_totali": consumo.total_tokens,
            "costo_usd": consumo.total_cost,
            "durata_s": italiane["durata_s"],
        })
        mlflow.log_dict({"italiane": italiane["errori_per_campo"], "estere": estere["errori_per_campo"]},
                        "errori_per_campo.json")
        mlflow.log_text(json.dumps(estere["dettaglio"], ensure_ascii=False, indent=1, default=str), "estere_dettaglio.json")
        mlflow.log_text(json.dumps(italiane["risultati"], ensure_ascii=False, indent=1, default=str),
                        "italiane_dettaglio.json")

    print(f"\nModello testo {config.MODELLO_TESTO}: italiane {italiane['corrette']}/{italiane['estrazioni']} "
          f"(rumore {italiane['rumore']:.0%}), estere {estere['corrette']}/{estere['fatture']} — "
          f"{consumo.total_tokens} token, ${consumo.total_cost:.4f}")
    print(f"Errori per campo: italiane {italiane['errori_per_campo']} · estere "
          f"{ {k: v for k, v in estere['errori_per_campo'].items() if v} }")


if __name__ == "__main__":
    main()
