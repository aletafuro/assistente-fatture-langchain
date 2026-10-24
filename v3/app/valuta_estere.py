"""
VALUTAZIONE SULLE FATTURE ESTERE DI PROVA (golden set estero)
============================================================

Esegue l'elaborazione del mese sulla cartella file_di_prova/estere (7 fatture inventate + estratti Amex e
UniCredit finti) e confronta, campo per campo, con valutazione/golden_set_estere.json.

Misura due cose diverse, da tenere separate:
   - LETTURA (il modello): fornitore, paese, partita IVA, numero, data, valuta, totale;
   - CONTI (Python): controvalore in euro e fonte del cambio (Amex, UniCredit, Banca d'Italia).

Uso:  uv run python app/valuta_estere.py      (le letture già fatte non si ripagano: sono salvate)
"""

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import config
import elabora_mese as em

CARTELLA = config.BASE / "file_di_prova" / "estere"
GOLDEN = config.BASE / "valutazione" / "golden_set_estere.json"
CAMPI_LETTURA = ["fornitore", "paese_fornitore", "partita_iva", "numero", "data_emissione", "valuta", "totale_cent"]


def _uguale(campo: str, a, b) -> bool:
    if campo == "fornitore":                       # la punteggiatura della forma societaria non conta
        return re.sub(r"[^a-z0-9]", "", str(a or "").lower()) == re.sub(r"[^a-z0-9]", "", str(b or "").lower())
    return a == b


def _fonte(testo: str) -> str:
    testo = (testo or "").lower()
    return next((f for f in ("amex", "unicredit", "bdi", "euro") if f in testo), "?")


def valuta() -> dict:
    import estratti_conto as ec
    ec.aggiungi_alias("nestbox", "CloudNest")      # come lo direbbe l'amministrazione in chat
    risultato = em.elabora(CARTELLA / "fatture", CARTELLA / "estratto_amex_prova_09-2026.xlsx",
                           CARTELLA / "estratto_unicredit_prova_09-2026.pdf")
    lette = {f["file"]: f for f in risultato["fatture"]}
    righe, errori_campo = [], {c: 0 for c in CAMPI_LETTURA + ["importo_eur", "fonte_cambio"]}
    for atteso in json.loads(GOLDEN.read_text(encoding="utf-8")):
        f = lette.get(atteso["file"], {})
        sbagliati = [c for c in CAMPI_LETTURA if not _uguale(c, f.get(c), atteso[c])]
        if f.get("importo_eur") is None or Decimal(str(f["importo_eur"])) != Decimal(atteso["importo_eur"]):
            sbagliati.append("importo_eur")
        if _fonte(f.get("fonte_cambio")) != atteso["fonte_cambio"]:
            sbagliati.append("fonte_cambio")
        for c in sbagliati:
            errori_campo[c] += 1
        righe.append({"file": atteso["file"], "ok": not sbagliati, "sbagliati": sbagliati,
                      "letto": {c: f.get(c) for c in CAMPI_LETTURA} | {"importo_eur": str(f.get("importo_eur")),
                                                                      "fonte_cambio": f.get("fonte_cambio")}})
    n = len(righe)
    return {"fatture": n, "corrette": sum(r["ok"] for r in righe),
            "accuratezza_lettura": sum(not any(c in CAMPI_LETTURA for c in r["sbagliati"]) for r in righe) / n,
            "accuratezza_euro": sum("importo_eur" not in r["sbagliati"] for r in righe) / n,
            "errori_per_campo": errori_campo, "dettaglio": righe}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    esito = valuta()
    for r in esito["dettaglio"]:
        print(("OK  " if r["ok"] else "NO  ") + r["file"] + ("" if r["ok"] else f"  sbagliati: {r['sbagliati']}  letto: {r['letto']}"))
    print(f"\nFatture estere corrette in tutto: {esito['corrette']}/{esito['fatture']} — lettura "
          f"{esito['accuratezza_lettura']:.0%}, controvalore in euro {esito['accuratezza_euro']:.0%}")


if __name__ == "__main__":
    main()
