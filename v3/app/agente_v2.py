"""
L'AGENTE DELLA V2 E IL ROUTER
=============================

Nella v2 l'agente NON gestisce più le fatture nuove: quelle passano dal grafo delle bozze
(percorso fisso, grafo_bozze.py). L'agente risponde a tutto il resto: domande, riepiloghi,
pagamenti, annullamenti, Excel, email al commercialista.

Da dove arrivano i suoi tool:
   - LETTURA  -> dal SERVER MCP (server_mcp.py): cerca, riepilogo, scadenze, fornitore più costoso
   - CONTENUTO-> dal RAG (rag_fatture.py): cosa c'è scritto nelle fatture
   - SCRITTURA-> tool locali della v1: pagare, annullare, Excel, email, riprova archiviazione.
                Restano locali di proposito: il server MCP è in sola lettura.

Memoria delle conversazioni su SQLite (AsyncSqliteSaver): sopravvive al riavvio del bot.
Tutto è asincrono: i tool MCP si chiamano solo con await.

Il ROUTER (pattern "routing"): prima di tutto, un LLM piccolo decide se un messaggio di testo
descrive una FATTURA NUOVA (-> grafo) oppure è una richiesta (-> agente).
"""

import os
import sys
from datetime import date
from pathlib import Path

import percorsi_v2 as P

import aiosqlite
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

import estratti_conto
import rag_fatture
import termini
from langchain_core.tools import tool
from strumenti_fatture import (annulla_fattura, esporta_riepilogo_excel, invia_riepilogo_al_commercialista,
                               riprova_archiviazione, segna_pagata)

SERVER_MCP = {
    "registro": {
        "command": sys.executable,
        "args": [str(Path(__file__).resolve().parent / "server_mcp.py")],
        "transport": "stdio",
        "env": dict(os.environ),      # passa al server anche CARTELLA_DATI e le altre impostazioni
    }
}
@tool
def ricorda_nome_sulla_carta(nome_sulla_carta: str, fornitore: str) -> str:
    """Ricorda che un nome che compare sull'estratto conto della carta (Amex, UniCredit) corrisponde a un
    fornitore con una ragione sociale diversa. Esempio: l'utente scrive "CodeWave è Fabrikam" ->
    nome_sulla_carta="CodeWave", fornitore="Fabrikam". Serve ad abbinare gli addebiti alle fatture."""
    return estratti_conto.aggiungi_alias(nome_sulla_carta, fornitore)


@tool
def imposta_termini_pagamento(fornitore: str, termine: str) -> str:
    """Salva i termini di pagamento di un fornitore, usati per lo scadenziario quando la fattura non ha una
    scadenza. Il termine si scrive come lo scrive l'amministrazione: "30 gg DF" (30 giorni data fattura),
    "60 gg DF", "30 gg FM" (fine mese). Esempio: "Tailspin si paga a 30 giorni" -> termine="30 gg DF"."""
    return termini.imposta(fornitore, termine)


TOOL_SCRITTURA = [segna_pagata, annulla_fattura, esporta_riepilogo_excel,
                  invia_riepilogo_al_commercialista, riprova_archiviazione,
                  ricorda_nome_sulla_carta, imposta_termini_pagamento]


def system_prompt() -> str:
    return f"""Sei l'assistente per le fatture fornitori di una piccola impresa italiana, su Telegram.
Oggi è il {date.today().isoformat()}. Rispondi in italiano, breve e chiaro, testo semplice (niente markdown).

1. Le fatture NUOVE non le registri tu: le gestisce un percorso guidato. Se l'utente vuole registrarne una,
   digli di mandarla (foto, PDF, vocale o dati scritti) e il percorso partirà da solo.
2. Per domande su COSA è stato acquistato o scritto nelle fatture usa cerca_nel_contenuto_delle_fatture;
   per totali, stato di pagamento e scadenze usa i tool del registro.
3. Non fare mai calcoli su importi o date: usa i tool.
4. Per pagare o annullare serve l'id: cercalo TU con cerca_fatture; se ne trovi più di uno, chiedi quale.
5. Prima di annullare una fattura o inviare l'email al commercialista, riassumi e chiedi conferma esplicita.
6. Se ti chiedono un'azione per cui non hai uno strumento, dillo chiaramente: non offrirti di farla.
7. Se un tool restituisce ERRORE, spiega il problema con parole semplici.
"""


@wrap_model_call
async def un_tool_alla_volta(richiesta, prosegui):
    impostazioni = {**richiesta.model_settings, "parallel_tool_calls": False}
    return await prosegui(richiesta.override(model_settings=impostazioni,
                                             system_message=SystemMessage(content=system_prompt())))


_agente = None
_connessione = None


async def prepara():
    """Da chiamare una volta all'avvio del bot: collega il server MCP e il database della memoria."""
    global _agente, _connessione
    tool_mcp = await MultiServerMCPClient(SERVER_MCP).get_tools()
    _connessione = await aiosqlite.connect(str(P.AGENTE_DB))
    _agente = create_agent(
        model="openai:gpt-4.1-mini",
        tools=tool_mcp + [rag_fatture.cerca_nel_contenuto_delle_fatture] + TOOL_SCRITTURA,
        system_prompt=system_prompt(),
        checkpointer=AsyncSqliteSaver(_connessione),
        middleware=[un_tool_alla_volta],
    )
    return [t.name for t in tool_mcp]


async def chiudi():
    if _connessione is not None:
        await _connessione.close()


async def chiedi(messaggio: str, id_conversazione: str) -> tuple:
    """Risposta dell'agente + eventuali file creati dai tool (es. l'Excel)."""
    configurazione = {"configurable": {"thread_id": id_conversazione}}
    prima = len((await _agente.aget_state(configurazione)).values.get("messages", []))
    risultato = await _agente.ainvoke({"messages": [{"role": "user", "content": messaggio}]}, configurazione)
    file_creati = [Path(m.content.removeprefix("FILE_CREATO: ").strip())
                   for m in risultato["messages"][prima:]
                   if m.type == "tool" and isinstance(m.content, str) and m.content.startswith("FILE_CREATO: ")]
    return risultato["messages"][-1].content, file_creati


# ---------------------------------------------------------------------------
# IL ROUTER
# ---------------------------------------------------------------------------
class Intento(BaseModel):
    nuova_fattura: bool = Field(description="True SOLO se il messaggio contiene i DATI CONCRETI di una fattura "
                                            "nuova da registrare: un nome di fornitore E almeno un importo o un "
                                            "numero di fattura (es. 'fattura Rossi n. 45, 500 euro + IVA'). "
                                            "False per domande, richieste di riepiloghi, pagamenti, saluti, "
                                            "commenti o spiegazioni che nominano i campi senza dare i valori "
                                            "(es. 'mi servono fornitore, p.iva e importo per la contabilità').")


_router = init_chat_model("openai:gpt-4.1-mini", temperature=0).with_structured_output(Intento)


def e_nuova_fattura(testo: str) -> bool:
    return _router.invoke(f"Messaggio dell'utente: {testo}").nuova_fattura
