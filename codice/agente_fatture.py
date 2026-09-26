"""
L'AGENTE DELLE FATTURE (create_agent)
======================================

L'agente = LLM + tool + un ciclo automatico: pensa -> chiama un tool -> guarda il risultato
-> ripete finché il lavoro è finito -> risponde.

  - system prompt: le "regole del mestiere" (mai registrare senza conferma, chiedere i dati
    mancanti, non fare calcoli, conferma prima di azioni irreversibili, ...);
  - memoria della conversazione: checkpointer + thread_id (con Telegram = id della chat);
  - middleware: un tool alla volta (niente chiamate in parallelo) e data di oggi sempre aggiornata.
"""

from datetime import date
from pathlib import Path


from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from strumenti_fatture import TOOL_ASSISTENTE

MODELLO_AGENTE = "openai:gpt-4.1-mini"


def system_prompt() -> str:
    return f"""Sei l'assistente per le fatture fornitori di una piccola impresa italiana, e parli con l'utente su Telegram.
Oggi è il {date.today().isoformat()}. Rispondi sempre in italiano, in modo breve e chiaro.
Scrivi testo semplice: niente markdown, niente asterischi, niente tabelle. Per gli elenchi usa il trattino.

REGOLE PER LE NUOVE FATTURE:
1. Quando ricevi un file o i dati di una nuova fattura, crea una bozza e mostra all'utente i dati estratti.
2. Se mancano dati, chiedili all'utente, uno o due alla volta. Non inventare mai un dato.
3. Se manca la data di scadenza e il programma propone una data, chiedi all'utente se va bene la proposta.
4. Registra una fattura (conferma_bozza) SOLO dopo che l'utente ha detto chiaramente di confermare o salvare.
5. Segnala sempre gli AVVISI restituiti dai tool (IVA non ordinaria, importi incoerenti, possibili duplicati,
   partita IVA non valida). Se è un possibile duplicato, chiedi all'utente se annullare la bozza.
   NON aggiungere controlli tuoi sui dati (lunghezza della partita IVA, somme, date): li fa già il
   programma in modo esatto. Se il tool non segnala avvisi, i dati sono formalmente corretti.
6. I messaggi che iniziano con "[VOCALE TRASCRITTO]" sono la trascrizione automatica di un vocale:
   possono contenere errori di ascolto, quindi mostra sempre i dati capiti e falli verificare.
   Per creare la bozza usa acquisisci_fattura_da_testo passando il testo trascritto e, come percorso_audio,
   il percorso del file audio indicato nel messaggio.
6b. Dopo la conferma, il programma archivia l'originale su Google Drive: riferisci l'esito all'utente.
   Se l'archiviazione è fallita, dillo chiaramente (la fattura è comunque registrata).

REGOLE PER IL COMMERCIALISTA:
6c. Prima di inviare il riepilogo al commercialista, riassumi periodo e numero di fatture e chiedi
   conferma esplicita: l'email non si può ritirare.
6d. Se l'utente vuole solo il file, usa esporta_riepilogo_excel: il programma glielo manda in chat.

REGOLE GENERALI:
7. Non fare mai calcoli su importi o date: usa i tool, che calcolano in modo esatto.
8. Per pagare o annullare una fattura serve il suo id: non chiederlo all'utente, cercalo TU con
   cerca_fatture usando il fornitore o il numero. Se trovi una sola fattura adatta, procedi; se ne trovi
   più di una, chiedi all'utente quale.
9. Prima di annullare una fattura già registrata, chiedi conferma all'utente.
10. Se la richiesta è ambigua (es. quale fattura, quale periodo), chiedi invece di indovinare.
11. Se un tool restituisce ERRORE, spiega il problema all'utente con parole semplici e suggerisci cosa fare.
"""


@wrap_model_call
def un_tool_alla_volta(richiesta, prosegui):
    """Impedisce chiamate ai tool in parallelo (es. modifica + conferma insieme)."""
    impostazioni = {**richiesta.model_settings, "parallel_tool_calls": False}
    return prosegui(richiesta.override(model_settings=impostazioni))


@wrap_model_call
def data_sempre_aggiornata(richiesta, prosegui):
    """Il bot può restare acceso più giorni: a ogni chiamata rimettiamo il prompt con la data di OGGI."""
    return prosegui(richiesta.override(system_message=SystemMessage(content=system_prompt())))


_memoria = InMemorySaver()

agente = create_agent(
    model=MODELLO_AGENTE,
    tools=TOOL_ASSISTENTE,
    system_prompt=system_prompt(),
    checkpointer=_memoria,
    middleware=[data_sempre_aggiornata, un_tool_alla_volta],
)


def chiedi_all_agente_con_file(messaggio: str, id_conversazione: str) -> tuple:
    """Come chiedi_all_agente, ma restituisce anche i file creati dai tool in questo turno
    (es. il file Excel del riepilogo), così il bot può mandarli all'utente."""
    configurazione = {"configurable": {"thread_id": id_conversazione}}
    prima = len(agente.get_state(configurazione).values.get("messages", []))
    risultato = agente.invoke({"messages": [{"role": "user", "content": messaggio}]}, configurazione)
    file_creati = []
    for m in risultato["messages"][prima:]:
        if m.type == "tool" and isinstance(m.content, str) and m.content.startswith("FILE_CREATO: "):
            file_creati.append(Path(m.content.removeprefix("FILE_CREATO: ").strip()))
    return risultato["messages"][-1].content, file_creati


def chiedi_all_agente(messaggio: str, id_conversazione: str) -> str:
    """Manda un messaggio all'agente e restituisce la sua risposta finale.
    id_conversazione: con Telegram è l'id della chat, così ogni utente ha la sua memoria."""
    return chiedi_all_agente_con_file(messaggio, id_conversazione)[0]
