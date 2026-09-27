"""
CONFRONTO MISURATO v1 / v2
==========================

Stessi scenari, stessi messaggi dell'utente, ripetuti N volte su:
   v1 = agente create_agent che gestisce anche le bozze (codice/agente_fatture.py)
   v2 = grafo delle bozze (percorso fisso) - codice_v2/grafo_bozze.py

Per ogni esecuzione si misura: esito corretto (controllando il REGISTRO, non la risposta a parole),
messaggi dell'utente necessari, chiamate all'LLM, token, secondi.

Lavora su una cartella dati TEMPORANEA: non tocca il registro vero. Drive, avvisi e RAG sono
disattivati (nessun file caricato, nessuna notifica).

Uso (dalla cartella del progetto):   python codice_v2/confronto_v1_v2.py [giri]
Scrive: valutazione/CONFRONTO_V1_V2.md
"""

import importlib
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

CARTELLA_TEMP = Path(tempfile.mkdtemp(prefix="confronto_v1_v2_"))
os.environ["CARTELLA_DATI"] = str(CARTELLA_TEMP)       # PRIMA di importare qualunque modulo del progetto

import percorsi_v2 as P  # noqa: E402

import agente_fatture  # noqa: E402  (v1)
import archivio  # noqa: E402
import avvisi  # noqa: E402
import bozze_fatture as boz  # noqa: E402
import grafo_bozze  # noqa: E402  (v2)
import rag_fatture  # noqa: E402
import registro_fatture as reg  # noqa: E402
from langchain_community.callbacks import get_openai_callback  # noqa: E402

archivio.archivia_fattura = lambda id_fattura: "(Drive disattivato nel confronto)"
avvisi.notifica = lambda *a, **k: []
rag_fatture.aggiungi = lambda fattura: None

COMPLETA = ("Fattura Alfa Servizi srl, partita IVA 01234567890, numero 10 del 10/09/2026, scadenza 10/10/2026, "
            "imponibile 100 euro, IVA 22 euro, totale 122 euro")
SENZA_SCADENZA = ("Fattura Beta Ufficio srl, partita IVA 02345678901, numero 20 del 12/09/2026, "
                  "imponibile 200 euro, IVA 44 euro, totale 244 euro")
SOPRA_SOGLIA = ("Fattura Gamma Consulenze srl, partita IVA 03456789012, numero 30 del 15/09/2026, scadenza 15/10/2026, "
                "imponibile 5.000 euro, IVA 1.100 euro, totale 6.100 euro")
RIAVVIO = "<<RIAVVIO>>"

# nome, messaggi dell'utente, controllo sul registro finale, pre-registrazione (per il duplicato)
SCENARI = [
    ("1. Fattura completa + conferma", [COMPLETA, "sì, registrala"],
     lambda r: len(r) == 1 and r[0]["totale_cent"] == 12200, False),
    ("2. Scadenza mancante, risposta e conferma nello stesso messaggio",
     [SENZA_SCADENZA, "Scade il 20 ottobre 2026. Poi salvala pure."],
     lambda r: len(r) == 1 and r[0]["data_scadenza"] == "2026-10-20", False),
    ("3. Riavvio del programma a metà bozza",
     [SENZA_SCADENZA, RIAVVIO, "va bene la data che proponi", "sì, salvala"],
     lambda r: len(r) == 1 and r[0]["data_scadenza"] == "2026-10-12", False),
    ("4. Duplicato", [COMPLETA, "sì, registrala"], lambda r: len(r) == 1, True),
    ("5. Importo sopra 5.000 €", [SOPRA_SOGLIA, "sì, registrala"],
     lambda r: len(r) == 1 and r[0]["totale_cent"] == 610000, False),
    ("6. L'utente rinuncia", [COMPLETA, "no, lascia perdere, non registrarla"], lambda r: len(r) == 0, False),
    ("7. Nessuna conferma data (sicurezza)", [COMPLETA], lambda r: len(r) == 0, False),
]
EXTRA_SI = 2   # se il sistema fa ancora domande a fine scenario, l'utente può rispondere "sì" fino a 2 volte


def azzera():
    reg.svuota_registro()
    boz.svuota_bozze()
    if P.BOZZE_APERTE.exists():
        P.BOZZE_APERTE.unlink()


def turno_v1(msg, thread):
    return agente_fatture.chiedi_all_agente(msg, thread)


def turno_v2(msg, chat):
    if grafo_bozze.bozza_aperta(chat):
        return grafo_bozze.rispondi(chat, msg)
    return grafo_bozze.avvia(chat, testo=msg)


def esegui(versione, scenario, giro):
    nome, messaggi, controllo, pre = scenario
    azzera()
    if pre:
        reg.registra_fattura({"fornitore": "Alfa Servizi srl", "partita_iva": "01234567890", "numero": "10",
                              "data_emissione": "2026-09-10", "data_scadenza": "2026-10-10",
                              "imponibile_cent": 10000, "iva_cent": 2200, "totale_cent": 12200})
    thread = f"{versione}-{nome[:2]}-{giro}-{datetime.now():%H%M%S%f}"
    turni, doppia, ultima = 0, False, ""
    inizio = time.time()
    with get_openai_callback() as cb:
        for msg in messaggi:
            if msg == RIAVVIO:
                if versione == "v1":
                    importlib.reload(agente_fatture)       # memoria della conversazione persa
                else:
                    grafo_bozze.ricostruisci()             # stesso database SQLite
                continue
            ultima = turno_v1(msg, thread) if versione == "v1" else turno_v2(msg, thread)
            turni += 1
            doppia = doppia or "sopra la soglia" in ultima.lower() and "conferm" in ultima.lower()
        for _ in range(EXTRA_SI):                          # il sistema chiede ancora qualcosa?
            if versione == "v2":
                ancora = grafo_bozze.bozza_aperta(thread)
            else:   # la v1 sta chiedendo una conferma (non un generico "vuoi altro?")
                basso = ultima.lower()
                ancora = "?" in basso and any(p in basso for p in ("confermi", "salvare", "registr", "va bene"))
            if not ancora or "7." in nome or "6." in nome:
                break
            ultima = turno_v1("sì", thread) if versione == "v1" else turno_v2("sì", thread)
            turni += 1
            doppia = doppia or "sopra la soglia" in ultima.lower() and "conferm" in ultima.lower()
    return {"ok": bool(controllo(reg.carica_registro())), "turni": turni, "chiamate": cb.successful_requests,
            "token": cb.total_tokens, "secondi": time.time() - inizio, "doppia": doppia}


def main(giri: int):
    risultati = {}
    for scenario in SCENARI:
        for versione in ("v1", "v2"):
            corse = [esegui(versione, scenario, g) for g in range(giri)]
            risultati[(scenario[0], versione)] = corse
            print(f"{scenario[0][:48]:48} {versione}: corretti {sum(c['ok'] for c in corse)}/{giri} | "
                  f"turni {sum(c['turni'] for c in corse) / giri:.1f} | chiamate LLM {sum(c['chiamate'] for c in corse) / giri:.1f} | "
                  f"token {sum(c['token'] for c in corse) / giri:,.0f} | {sum(c['secondi'] for c in corse) / giri:.1f}s")
    scrivi_rapporto(risultati, giri)
    shutil.rmtree(CARTELLA_TEMP, ignore_errors=True)


def scrivi_rapporto(risultati, giri):
    media = lambda corse, k: sum(c[k] for c in corse) / len(corse)
    righe = ["# Confronto misurato v1 / v2", "",
             f"Eseguito il {datetime.now():%d/%m/%Y %H:%M} · {len(SCENARI)} scenari × 2 versioni × {giri} giri. "
             "Un'esecuzione è **corretta** se il **registro** finale è quello atteso (non conta la risposta a parole).",
             "", "| Scenario | Corretti v1 | Corretti v2 | Messaggi utente v1 / v2 | Chiamate LLM v1 / v2 | Token v1 / v2 | Secondi v1 / v2 |",
             "|---|---|---|---|---|---|---|"]
    tot = {"v1": [], "v2": []}
    for nome, *_ in SCENARI:
        a, b = risultati[(nome, "v1")], risultati[(nome, "v2")]
        tot["v1"] += a
        tot["v2"] += b
        righe.append(f"| {nome} | {sum(c['ok'] for c in a)}/{giri} | {sum(c['ok'] for c in b)}/{giri} | "
                     f"{media(a, 'turni'):.1f} / {media(b, 'turni'):.1f} | {media(a, 'chiamate'):.1f} / {media(b, 'chiamate'):.1f} | "
                     f"{media(a, 'token'):,.0f} / {media(b, 'token'):,.0f} | {media(a, 'secondi'):.1f} / {media(b, 'secondi'):.1f} |")
    righe.append(f"| **Totale** | **{sum(c['ok'] for c in tot['v1'])}/{len(tot['v1'])}** | "
                 f"**{sum(c['ok'] for c in tot['v2'])}/{len(tot['v2'])}** | {media(tot['v1'], 'turni'):.1f} / {media(tot['v2'], 'turni'):.1f} | "
                 f"{media(tot['v1'], 'chiamate'):.1f} / {media(tot['v2'], 'chiamate'):.1f} | "
                 f"{media(tot['v1'], 'token'):,.0f} / {media(tot['v2'], 'token'):,.0f} | "
                 f"{media(tot['v1'], 'secondi'):.1f} / {media(tot['v2'], 'secondi'):.1f} |")
    doppia = {v: sum(c["doppia"] for c in risultati[(SCENARI[4][0], v)]) for v in ("v1", "v2")}
    righe += ["", f"Doppia conferma chiesta nello scenario 5 (sopra 5.000 €): v1 {doppia['v1']}/{giri}, v2 {doppia['v2']}/{giri}.",
              "", "Modelli: v1 agente gpt-4.1-mini; v2 estrazione gpt-4o-mini + interpretazione risposte gpt-4.1-mini "
              "(le risposte ovvie come \"sì\" non chiamano l'LLM).", ""]
    (P.config.VALUTAZIONE / "CONFRONTO_V1_V2.md").write_text("\n".join(righe), encoding="utf-8")
    print("\n-> valutazione/CONFRONTO_V1_V2.md")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
