"""
IL PERCORSO DELLE BOZZE COME GRAFO LANGGRAPH (v2)
=================================================

Nella v1 la bozza era gestita dall'agente (create_agent): era l'LLM a decidere quando chiedere
un dato, quando modificare e quando confermare, guidato dal system prompt e da un middleware.
Nella v2 il percorso è SCRITTO NEL CODICE: l'LLM legge la fattura e interpreta le risposte
dell'utente, ma la strada la scelgono regole Python.

   START -> estrai -> controlla --(manca un dato)--> chiedi_mancante --+
                         ^                                            |
                         +-------------(ricontrolla)------------------+
                         |
                         +--(completa)--> chiedi_conferma --(modifica)--> controlla
                                               |--(annulla)--> annulla -> END
                                               |--(conferma, sotto soglia)--> registra -> END
                                               +--(conferma, sopra soglia)--> doppia_conferma -> registra / annulla

- interrupt(): il grafo si ferma per fare una domanda; riparte con Command(resume=risposta).
- SqliteSaver: lo stato del grafo sta su disco. Una bozza a metà sopravvive al riavvio del bot,
  anche se l'utente risponde il giorno dopo (nella v1 si salvava la bozza, ma non la conversazione).
- I controlli (mancanti, duplicati, P.IVA, IVA non ordinaria, proposta di scadenza) sono QUELLI
  DELLA V1 (bozze_fatture._aggiorna_controlli): stessa logica, cambia solo chi decide il percorso.
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, TypedDict

import percorsi_v2 as P  # noqa: F401  (deve stare prima dei moduli della v1)

import anagrafica_esteri
import archivio
import avvisi
import bozze_fatture as boz
import config
import registro_fatture as reg
from estrazione import ErroreEstrazione, estrai_da_file, estrai_da_testo
from fatture_comuni import (PIVA_ESTERO_ASSENTE, e_estero, euro_in_centesimi, normalizza_data, normalizza_paese,
                            normalizza_piva, normalizza_valuta)
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

SOGLIA_DOPPIA_CONFERMA_CENT = int(float(__import__("os").getenv("DOPPIA_CONFERMA_EURO", "5000")) * 100)
CAMPI = boz.CAMPI_MODIFICABILI
ETICHETTE = {"fornitore": "il fornitore", "partita_iva": "la partita IVA", "numero": "il numero della fattura",
             "data_emissione": "la data di emissione", "data_scadenza": "la data di scadenza",
             "imponibile_cent": "l'imponibile", "iva_cent": "l'IVA", "totale_cent": "il totale",
             "regime_iva": "il regime IVA", "paese_fornitore": "il paese del fornitore (es. IT, NL, US)",
             "indirizzo_fornitore": "l'indirizzo del fornitore", "valuta": "la valuta (EUR, USD, GBP...)",
             "cambio_manuale": "il cambio Banca d'Italia del giorno della fattura (quantità di valuta per 1 euro)"}
CampoBozza = Literal["fornitore", "paese_fornitore", "indirizzo_fornitore", "partita_iva", "numero",
                     "data_emissione", "data_scadenza", "valuta", "imponibile_cent", "iva_cent", "totale_cent",
                     "regime_iva", "cambio_manuale"]


# ---------------------------------------------------------------------------
# LO STATO
# ---------------------------------------------------------------------------
class StatoBozza(TypedDict, total=False):
    percorso_originale: Optional[str]   # file ricevuto (PDF, foto, audio, o .txt creato per il testo)
    testo: Optional[str]                # testo scritto o trascritto (se non è un file da leggere)
    nota_utente: Optional[str]          # testo scritto INSIEME al file (didascalia), es. "data emissione 01/09/2026"
    testo_documento: Optional[str]      # testo del PDF, per i controlli Python (nostra P.IVA, rate del fornitore)
    dati: dict
    mancanti: list
    avvisi: list
    proposta_scadenza: Optional[str]
    decisione: str                      # conferma / annulla / modifica / errore
    nota: Optional[str]                 # messaggio da premettere alla prossima domanda (es. valore non valido)
    esito: str


# ---------------------------------------------------------------------------
# L'LLM INTERPRETA LE RISPOSTE (ma non decide la strada)
# ---------------------------------------------------------------------------
class Interpretazione(BaseModel):
    azione: Literal["conferma", "annulla", "valore", "assente", "altro"] = Field(
        description="conferma = accetta/approva; annulla = rinuncia ESPLICITAMENTE alla fattura "
                    "('annulla', 'non registrarla'); valore = fornisce o corregge un dato; "
                    "assente = dice che il dato richiesto NON C'È sulla fattura ('nessuna', 'non c'è', "
                    "'nessuna data di scadenza', 'non ha partita IVA'): NON è un annullamento; "
                    "altro = risposta non pertinente")
    campo: Optional[CampoBozza] = Field(
        default=None, description="Il campo a cui si riferisce il valore (per gli importi: imponibile_cent, "
                                  "iva_cent, totale_cent)")
    valore: Optional[str] = Field(default=None, description="Il valore COPIATO come l'ha scritto l'utente, "
                                                            "senza convertirlo (es. '20 ottobre 2026', '1.200,00')")


_interprete = init_chat_model(f"openai:{config.MODELLO_INTERPRETE}", temperature=0).with_structured_output(Interpretazione)


def _esempi_interprete() -> str:
    """Esempi con l'interpretazione giusta, scelti con DSPy (app/interprete_esempi.json, vedi ottimizza_interprete.py).
    Contengono le regole dell'amministrazione: "nessuna" = il dato non c'è, "non lo so" = altro, ecc."""
    percorso = Path(__file__).resolve().parent / "interprete_esempi.json"
    if not percorso.exists():
        return ""
    righe = [f"- campo chiesto: {e['campo_atteso']} | risposta: \"{e['risposta']}\" -> azione={e['azione']}, "
             f"campo={e['campo']}, valore={e['valore']}" for e in json.loads(percorso.read_text(encoding="utf-8"))]
    return "Esempi di risposte con l'interpretazione giusta:\n" + "\n".join(righe) + "\n\n"


_ESEMPI = _esempi_interprete()
_SI = {"sì", "si", "ok", "okay", "conferma", "confermo", "va bene", "salva", "salvala", "registra", "procedi"}
_ANNULLA = {"annulla", "annullala", "lascia perdere", "cancella"}


def interpreta(domanda: str, risposta: str, campo_atteso: Optional[str] = None) -> Interpretazione:
    pulita = risposta.strip().lower().rstrip(".!")
    if pulita in _SI:                                   # risposte ovvie: niente chiamata all'LLM
        return Interpretazione(azione="conferma")
    if pulita in _ANNULLA:
        return Interpretazione(azione="annulla")
    return _interprete.invoke(
        f"{_ESEMPI}Domanda fatta all'utente: {domanda}\nCampo atteso (se è una richiesta di dato): {campo_atteso}\n"
        f"Risposta dell'utente: {risposta}\nInterpreta la risposta.")


def converti(campo: str, valore: str, dati: Optional[dict] = None):
    """Python converte (l'LLM ha solo copiato). None = valore non valido."""
    paese = (dati or {}).get("paese_fornitore")
    try:
        if campo in boz.CAMPI_IMPORTO:
            return euro_in_centesimi(valore)
        if campo in boz.CAMPI_DATA:
            return normalizza_data(valore, paese)
        if campo == "regime_iva":
            return valore if valore in boz.REGIMI_IVA else None
        if campo == "partita_iva":
            return normalizza_piva(valore, paese)[0]
        if campo == "paese_fornitore":
            return normalizza_paese(valore)
        if campo == "valuta":
            return normalizza_valuta(valore)
        if campo == "cambio_manuale":
            numero = float(valore.replace(",", "."))
            return str(numero) if numero > 0 else None
        return valore.strip() or None
    except Exception:
        return None


def _descrivi(stato: StatoBozza) -> str:
    d, euro = stato["dati"], reg.centesimi_in_euro
    valuta = d.get("valuta") or "?"
    in_valuta = lambda c: "?" if d.get(c) is None else euro(d[c]).replace("€", valuta)
    righe = [f"- Fornitore: {d.get('fornitore')} ({d.get('paese_fornitore') or '?'}) - P.IVA {d.get('partita_iva')}",
             f"- Fattura n. {d.get('numero')} del {d.get('data_emissione')}, scadenza {d.get('data_scadenza')}"
             + (" (nessuna scadenza sulla fattura)" if d.get("scadenza_assente") else ""),
             f"- Imponibile {in_valuta('imponibile_cent')} + IVA {in_valuta('iva_cent')} = totale "
             f"{in_valuta('totale_cent')} (regime IVA: {str(d.get('regime_iva')).replace('_', ' ')})"]
    if valuta not in ("EUR", "?") and d.get("totale_eur_cent") is not None:
        righe.append(f"- In euro (cambio BdI {d.get('cambio_bdi')} del {d.get('data_cambio')}): imponibile "
                     f"{euro(d.get('imponibile_eur_cent'))} + IVA {euro(d.get('iva_eur_cent'))} = "
                     f"totale {euro(d.get('totale_eur_cent'))}")
    righe += [f"AVVISO: {a}" for a in stato.get("avvisi", [])]
    return "\n".join(righe)


# ---------------------------------------------------------------------------
# I NODI
# ---------------------------------------------------------------------------
def estrai(stato: StatoBozza) -> dict:
    try:
        if stato.get("testo"):
            dati = estrai_da_testo(stato["testo"], Path(stato["percorso_originale"]).name)
        else:
            dati = estrai_da_file(stato["percorso_originale"])
    except ErroreEstrazione as errore:
        return {"decisione": "errore", "esito": f"Non ho potuto leggere la fattura: {errore}"}
    testo_documento = dati.get("testo")
    dati = {c: dati.get(c) for c in CAMPI} | {"file": dati.get("file"), "tipo_documento": dati.get("tipo_documento"),
                                               "percorso_originale": stato["percorso_originale"]}
    dati["regime_iva"] = dati["regime_iva"] or "ordinario"
    # Testo scritto insieme al file (in prova: PDF + "data emissione 01/09/2026", e il dato veniva ignorato):
    # completa SOLO i campi che la lettura del file ha lasciato vuoti.
    if stato.get("nota_utente"):
        try:
            dalla_nota = estrai_da_testo(stato["nota_utente"], "nota")
            for campo in CAMPI:
                if campo != "regime_iva" and dati.get(campo) in (None, "") and dalla_nota.get(campo) not in (None, ""):
                    dati[campo] = dalla_nota[campo]
        except ErroreEstrazione:
            pass
    return {"dati": dati, "decisione": "", "testo_documento": testo_documento}


def controlla(stato: StatoBozza) -> dict:
    from fatture_comuni import piva_cliente_presente
    b = {"dati": dict(stato["dati"])}
    boz._aggiorna_controlli(b)                 # stessi controlli della v1 (+ estero, valuta, anagrafica)
    if piva_cliente_presente(stato.get("testo_documento")) is False:
        b["avvisi"].append("Sulla fattura manca la nostra partita IVA: chiedi al fornitore di correggerla.")
    return {"dati": b["dati"], "mancanti": b["mancanti"], "avvisi": b["avvisi"],
            "proposta_scadenza": b["proposta_scadenza"]}


def _dato_assente(stato: StatoBozza, campo: str) -> dict:
    """L'utente dice che il dato NON C'È sulla fattura: per alcuni campi c'è una regola, per gli altri no."""
    dati = stato["dati"]
    if campo == "data_scadenza":
        return {"dati": dati | {"scadenza_assente": True}, "decisione": "",
                "nota": "Ok, nessuna scadenza: uso la data della fattura."}
    if campo == "partita_iva" and e_estero(dati.get("paese_fornitore")):
        return {"dati": dati | {"partita_iva": PIVA_ESTERO_ASSENTE}, "decisione": "",
                "nota": f"Ok, fornitore estero senza partita IVA: uso il codice {PIVA_ESTERO_ASSENTE}."}
    return {"decisione": "", "nota": f"Mi serve comunque {ETICHETTE[campo]} per registrare la fattura "
                                     "(se non vuoi registrarla scrivi \"annulla\")."}


def chiedi_mancante(stato: StatoBozza) -> dict:
    campo = stato["mancanti"][0]
    if campo == "data_scadenza" and stato.get("proposta_scadenza"):
        domanda = (f"Sulla fattura non trovo la data di scadenza. Propongo il {stato['proposta_scadenza']} "
                   f"(emissione + 30 giorni): va bene, mi dici un'altra data, o scrivi \"nessuna\"?")
    elif campo == "cambio_manuale":
        domanda = (f"Non trovo il cambio Banca d'Italia {stato['dati'].get('valuta')}/EUR del "
                   f"{stato['dati'].get('data_emissione')}: me lo dici? (quantità di valuta per 1 euro, es. 1,1590)")
    else:
        domanda = f"Non trovo {ETICHETTE[campo]}: me lo dici?"
    if stato.get("nota"):
        domanda = f"{stato['nota']} {domanda}"
    risposta = interrupt(domanda)

    capito = interpreta(domanda, risposta, campo)
    if capito.azione == "annulla":
        return {"decisione": "annulla", "nota": None}
    if capito.azione == "assente":
        return _dato_assente(stato, campo)
    if capito.azione == "conferma" and campo == "data_scadenza" and stato.get("proposta_scadenza"):
        return {"dati": stato["dati"] | {"data_scadenza": stato["proposta_scadenza"]}, "nota": None, "decisione": ""}
    if capito.azione == "valore" and capito.valore:
        campo_dato = capito.campo or campo
        valore = converti(campo_dato, capito.valore, stato["dati"])
        if valore is not None:
            return {"dati": stato["dati"] | {campo_dato: valore}, "nota": None, "decisione": ""}
    return {"nota": "Non ho capito il valore.", "decisione": ""}


def chiedi_conferma(stato: StatoBozza) -> dict:
    domanda = (f"Ecco i dati della fattura:\n{_descrivi(stato)}\n\n"
               f"La registro? Puoi anche correggere un dato (es. \"la scadenza è il 30/10/2026\") o annullare.")
    if stato.get("nota"):
        domanda = f"{stato['nota']}\n{domanda}"
    capito = interpreta(domanda, interrupt(domanda))
    if capito.azione == "assente" and capito.campo:
        risultato = _dato_assente(stato, capito.campo)
        return risultato | {"decisione": "modifica"}
    if capito.azione == "valore" and capito.campo and capito.valore:
        valore = converti(capito.campo, capito.valore, stato["dati"])
        if valore is None:
            return {"decisione": "modifica", "nota": f"Non ho capito il valore per {ETICHETTE[capito.campo]}."}
        return {"dati": stato["dati"] | {capito.campo: valore}, "decisione": "modifica",
                "nota": f"Ho corretto {ETICHETTE[capito.campo]}."}
    if capito.azione in ("conferma", "annulla"):
        return {"decisione": capito.azione, "nota": None}
    return {"decisione": "modifica", "nota": "Non ho capito: rispondi sì, no, oppure correggi un dato."}


def _totale_euro(stato: StatoBozza) -> int:
    """La soglia della doppia conferma è in euro: per le fatture in valuta conta il totale convertito."""
    d = stato["dati"]
    return d.get("totale_eur_cent") if d.get("totale_eur_cent") is not None else (d.get("totale_cent") or 0)


def doppia_conferma(stato: StatoBozza) -> dict:
    euro = reg.centesimi_in_euro
    domanda = (f"ATTENZIONE: la fattura è di {euro(_totale_euro(stato))}, sopra la soglia di "
               f"{euro(SOGLIA_DOPPIA_CONFERMA_CENT)}. Confermi di nuovo la registrazione?")
    capito = interpreta(domanda, interrupt(domanda))
    return {"decisione": "conferma" if capito.azione == "conferma" else "annulla"}


def registra(stato: StatoBozza) -> dict:
    esito = reg.registra_fattura(stato["dati"])
    if esito["esito"] != "registrata":
        return {"esito": f"Non registrata. {esito['messaggio']}"}
    righe = [esito["messaggio"], *[f"AVVISO: {a}" for a in esito["avvisi"]],
             archivio.archivia_fattura(esito["id"])]
    try:                                        # fornitore estero: scheda in anagrafica (creata o aggiornata)
        righe += [f"ANAGRAFICA: {a}" for a in anagrafica_esteri.aggiorna_da_fattura(reg.trova_fattura(esito["id"]))]
    except Exception as errore:
        righe.append(f"AVVISO: anagrafica fornitori esteri non aggiornata ({errore}).")
    if config.SCADENZIARIO_ANNUALE:             # amministrazione: ogni fattura ricevuta va nello scadenziario
        try:
            import scadenziario
            voce = scadenziario.voce_da_fattura(stato["dati"] | {"testo": stato.get("testo_documento")},
                                                stato.get("nota_utente"))
            righe.append(f"SCADENZIARIO: {scadenziario.aggiungi(voce)}")
        except Exception as errore:
            righe.append(f"AVVISO: scadenziario non aggiornato ({errore}).")
    sopra = avvisi.controlla_importo(reg.trova_fattura(esito["id"]))
    if sopra:
        righe.append(f"AVVISO SOGLIA: {sopra}")
    try:                                        # il RAG impara la fattura nuova (se non riesce, pazienza)
        import rag_fatture
        rag_fatture.aggiungi(reg.trova_fattura(esito["id"]))
    except Exception:
        pass
    return {"esito": "\n".join(r for r in righe if r)}


def annulla(stato: StatoBozza) -> dict:
    return {"esito": "Bozza annullata: non ho registrato niente."}


# ---------------------------------------------------------------------------
# LE REGOLE (archi condizionali) - qui si decide la strada, in Python
# ---------------------------------------------------------------------------
def dopo_estrai(stato) -> Literal["controlla", "__end__"]:
    return END if stato.get("decisione") == "errore" else "controlla"


def dopo_controlla(stato) -> Literal["chiedi_mancante", "chiedi_conferma"]:
    return "chiedi_mancante" if stato["mancanti"] else "chiedi_conferma"


def dopo_mancante(stato) -> Literal["controlla", "annulla"]:
    return "annulla" if stato.get("decisione") == "annulla" else "controlla"


def dopo_conferma(stato) -> Literal["controlla", "annulla", "doppia_conferma", "registra"]:
    if stato["decisione"] == "annulla":
        return "annulla"
    if stato["decisione"] == "modifica":
        return "controlla"
    if _totale_euro(stato) >= SOGLIA_DOPPIA_CONFERMA_CENT:
        return "doppia_conferma"
    return "registra"


def dopo_doppia(stato) -> Literal["registra", "annulla"]:
    return "registra" if stato["decisione"] == "conferma" else "annulla"


def _costruisci():
    g = StateGraph(StatoBozza)
    for nome, fn in [("estrai", estrai), ("controlla", controlla), ("chiedi_mancante", chiedi_mancante),
                     ("chiedi_conferma", chiedi_conferma), ("doppia_conferma", doppia_conferma),
                     ("registra", registra), ("annulla", annulla)]:
        g.add_node(nome, fn)
    g.add_edge(START, "estrai")
    g.add_conditional_edges("estrai", dopo_estrai)
    g.add_conditional_edges("controlla", dopo_controlla)
    g.add_conditional_edges("chiedi_mancante", dopo_mancante)
    g.add_conditional_edges("chiedi_conferma", dopo_conferma)
    g.add_conditional_edges("doppia_conferma", dopo_doppia)
    g.add_edge("registra", END)
    g.add_edge("annulla", END)
    connessione = sqlite3.connect(str(P.GRAFO_DB), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(connessione))


grafo = _costruisci()
_lucchetto = threading.Lock()           # una sola operazione sul grafo alla volta (il bot è concorrente)


def ricostruisci() -> None:
    """Simula un riavvio: nuovo grafo, stesso database (usato dai test)."""
    global grafo
    grafo = _costruisci()


# ---------------------------------------------------------------------------
# INTERFACCIA PER IL BOT: una bozza aperta per chat
# ---------------------------------------------------------------------------
def _aperte() -> dict:
    return json.loads(P.BOZZE_APERTE.read_text(encoding="utf-8")) if P.BOZZE_APERTE.exists() else {}


def _salva_aperte(aperte: dict) -> None:
    P.BOZZE_APERTE.write_text(json.dumps(aperte, indent=2), encoding="utf-8")


def bozza_aperta(chat_id: str) -> bool:
    return str(chat_id) in _aperte()


def domanda_in_sospeso(chat_id: str) -> Optional[str]:
    thread = _aperte().get(str(chat_id))
    if not thread:
        return None
    stato = grafo.get_state({"configurable": {"thread_id": thread}})
    for task in stato.tasks:
        for intr in task.interrupts:
            return intr.value
    return None


def _esegui(chat_id: str, thread: str, ingresso) -> str:
    risultato = grafo.invoke(ingresso, {"configurable": {"thread_id": thread}})
    aperte = _aperte()
    if "__interrupt__" in risultato:
        aperte[str(chat_id)] = thread
        _salva_aperte(aperte)
        return risultato["__interrupt__"][0].value
    aperte.pop(str(chat_id), None)
    _salva_aperte(aperte)
    return risultato.get("esito", "Fatto.")


def avvia(chat_id: str, percorso: Optional[str] = None, testo: Optional[str] = None,
          nota_utente: Optional[str] = None) -> str:
    """Nuova fattura. Se arriva come testo scritto, l'originale da archiviare è un .txt col messaggio.
    nota_utente = testo scritto insieme al file (didascalia di Telegram)."""
    if percorso is None:
        percorso = config.RICEVUTI / f"testo_{datetime.now():%Y%m%d_%H%M%S}.txt"
        percorso.write_text(testo, encoding="utf-8")
    thread = f"{chat_id}-{datetime.now():%Y%m%d%H%M%S%f}"
    with _lucchetto:
        return _esegui(chat_id, thread, {"percorso_originale": str(percorso), "testo": testo,
                                         "nota_utente": nota_utente})


def rispondi(chat_id: str, risposta: str) -> str:
    """Risposta dell'utente alla domanda in sospeso: il grafo riparte da dove si era fermato."""
    thread = _aperte().get(str(chat_id))
    if not thread:
        return "Non c'è nessuna fattura in attesa di risposta."
    with _lucchetto:
        return _esegui(chat_id, thread, Command(resume=risposta))
