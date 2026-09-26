"""
I TOOL DELL'ASSISTENTE
======================

Un TOOL è una normale funzione Python con sopra la "decorazione"  @tool.
@tool la trasforma in qualcosa che l'LLM può CHIEDERE di usare.

Attenzione: l'LLM NON esegue mai la funzione da solo (function calling):
   1. all'LLM mostriamo l'ELENCO dei tool: nome + descrizione + parametri
   2. l'utente chiede "quanto ho speso a settembre?"
   3. l'LLM risponde: "vorrei chiamare il tool riepilogo con tipo='mese', anno=2026, numero=9"
   4. il programma esegue la funzione e ridà il risultato all'LLM
   5. l'LLM usa il risultato per rispondere all'utente a parole
L'agente (create_agent, in agente_fatture.py) ripete i passi 3-4-5 da solo finché il lavoro è finito.

Le 3 cose che l'LLM vede di ogni tool, quindi da scrivere con cura:
   - il NOME della funzione        -> deve dire cosa fa
   - la DOCSTRING (tra """ """)    -> QUANDO usarlo. È un prompt, come le description di Pydantic!
   - i PARAMETRI con il loro tipo  -> cosa deve passare (int = numero, str = testo, Literal = scelta fissa)

Dentro ogni tool NON c'è logica nuova: chiamiamo le funzioni di registro_fatture.py.
Il tool è solo la "maniglia" che permette all'LLM di afferrarle.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from langchain.tools import tool

import config
import registro_fatture as reg


@tool
def cerca_fatture(testo: str = "", stato: Literal["tutte", "da_pagare", "pagata", "annullata"] = "tutte") -> str:
    """Cerca fatture nel registro. Usalo per trovare l'id di una fattura (es. F0003) prima di
    pagarla o annullarla, o per elencare le fatture da pagare, pagate o annullate.

    Args:
        testo: parte del nome del fornitore o del numero fattura; vuoto per non filtrare.
        stato: filtra per stato della fattura.
    """
    return reg.cerca_fatture(testo, stato)


@tool
def segna_pagata(id_fattura: str, data_pagamento: Optional[str] = None) -> str:
    """Segna una fattura come pagata.

    Args:
        id_fattura: id della fattura nel registro, es. 'F0003'. Se non lo conosci, usa prima cerca_fatture.
        data_pagamento: data del pagamento in formato AAAA-MM-GG; se non indicata si usa oggi.
    """
    return reg.segna_pagata(id_fattura, data_pagamento)


@tool
def annulla_fattura(id_fattura: str, motivo: str) -> str:
    """Annulla una fattura (annullamento logico: esce dai totali ma resta nello storico).
    Usalo solo se l'utente chiede esplicitamente di annullare una fattura.

    Args:
        id_fattura: id della fattura nel registro, es. 'F0003'. Se non lo conosci, usa prima cerca_fatture.
        motivo: perché viene annullata (es. 'emessa per errore', 'sostituita da nota di credito').
    """
    return reg.annulla_fattura(id_fattura, motivo)


@tool
def riepilogo(tipo: Literal["mese", "trimestre", "anno"], anno: int, numero: Optional[int] = None) -> str:
    """Calcola il riepilogo delle fatture attive di un periodo: numero di fatture, imponibile,
    IVA, totale, quanto resta da pagare, totale per fornitore, casi IVA da verificare.

    Args:
        tipo: 'mese', 'trimestre' oppure 'anno'.
        anno: anno a 4 cifre, es. 2026.
        numero: numero del mese (1-12) o del trimestre (1-4); non serve se tipo='anno'.
    """
    return reg.riepilogo(tipo, anno, numero)


@tool
def fatture_in_scadenza(entro_giorni: int = 30, data_riferimento: Optional[str] = None) -> str:
    """Elenca le fatture ancora da pagare che scadono entro un certo numero di giorni
    (comprese quelle già scadute).

    Args:
        entro_giorni: quanti giorni guardare in avanti, es. 7 o 30.
        data_riferimento: data da cui contare, formato AAAA-MM-GG; se non indicata si usa oggi.
    """
    return reg.fatture_in_scadenza(entro_giorni, data_riferimento)


TOOL_REGISTRO = [cerca_fatture, segna_pagata, annulla_fattura, riepilogo, fatture_in_scadenza]


# ===========================================================================
# I TOOL DELLE BOZZE (estrazione assistita)
# ===========================================================================
# Stesso schema: la logica è in bozze_fatture.py ed estrazione.py, qui solo le "maniglie".
# Nota le docstring: sono loro a dire all'agente l'ORDINE giusto
# (prima la bozza, poi i dati mancanti, poi la conferma ESPLICITA dell'utente).

import bozze_fatture as boz
from estrazione import ErroreEstrazione, estrai_da_file, estrai_da_testo

CampoBozza = Literal["fornitore", "partita_iva", "numero", "data_emissione", "data_scadenza",
                     "imponibile_cent", "iva_cent", "totale_cent", "regime_iva"]


@tool
def acquisisci_fattura_da_file(percorso_file: str) -> str:
    """Legge una fattura da un file (PDF oppure foto JPG/PNG), ne estrae i dati e crea una BOZZA.
    La bozza NON è ancora registrata: va mostrata all'utente, completata e confermata.

    Args:
        percorso_file: percorso completo del file ricevuto.
    """
    try:
        dati = estrai_da_file(percorso_file)
    except ErroreEstrazione as errore:
        return f"ERRORE: {errore}"
    return boz.crea_bozza(dati, origine=Path(percorso_file).name, percorso_originale=percorso_file)


CARTELLA_RICEVUTI = config.RICEVUTI


@tool
def acquisisci_fattura_da_testo(testo: str, percorso_audio: Optional[str] = None) -> str:
    """Crea una BOZZA di fattura a partire da dati scritti o dettati dall'utente
    (es. 'fattura di Rossi srl n. 12 del 3 settembre, 500 euro più IVA').
    Usalo solo quando l'utente descrive una NUOVA fattura a parole.

    Args:
        testo: il testo dell'utente con i dati della fattura, copiato così com'è.
        percorso_audio: se i dati vengono da un vocale, il percorso del file audio indicato nel messaggio.
    """
    if percorso_audio and Path(percorso_audio).exists():
        originale, origine = percorso_audio, "vocale"
    else:
        # Scritta in chat: l'"originale" da archiviare è il testo stesso, salvato in un .txt.
        CARTELLA_RICEVUTI.mkdir(exist_ok=True)
        originale = CARTELLA_RICEVUTI / f"testo_{datetime.now():%Y%m%d_%H%M%S}.txt"
        originale.write_text(testo, encoding="utf-8")
        origine = "testo"
    try:
        dati = estrai_da_testo(testo)
    except ErroreEstrazione as errore:
        return f"ERRORE: {errore}"
    return boz.crea_bozza(dati, origine=origine, percorso_originale=originale)


@tool
def mostra_bozza(id_bozza: str) -> str:
    """Mostra i dati attuali di una bozza, i dati mancanti e gli avvisi.

    Args:
        id_bozza: id della bozza, es. 'B0001'.
    """
    return boz.mostra_bozza(id_bozza)


@tool
def elenca_bozze_aperte() -> str:
    """Elenca le bozze non ancora confermate né annullate (anche di sessioni precedenti)."""
    return boz.elenca_bozze_aperte()


@tool
def modifica_bozza(id_bozza: str, campo: CampoBozza, valore: str) -> str:
    """Modifica o completa un campo di una bozza con il valore dato dall'utente.
    Passa il valore COSÌ COME L'HA SCRITTO l'utente (es. '1.200,00' o '15/10/2026'):
    la conversione in centesimi e in data la fa il programma, non farla tu.

    Args:
        id_bozza: id della bozza, es. 'B0001'.
        campo: il campo da modificare (per gli importi usa imponibile_cent, iva_cent, totale_cent).
        valore: il nuovo valore come testo.
    """
    return boz.modifica_bozza(id_bozza, campo, valore)


@tool
def conferma_bozza(id_bozza: str) -> str:
    """Registra DEFINITIVAMENTE la bozza nel registro delle fatture.
    Usalo SOLO dopo che l'utente ha visto i dati e ha detto esplicitamente di confermare/salvare.

    Args:
        id_bozza: id della bozza, es. 'B0001'.
    """
    return boz.conferma_bozza(id_bozza)


@tool
def annulla_bozza(id_bozza: str) -> str:
    """Scarta una bozza senza registrarla (es. l'utente ha mandato il file sbagliato o è un duplicato).

    Args:
        id_bozza: id della bozza, es. 'B0001'.
    """
    return boz.annulla_bozza(id_bozza)


TOOL_BOZZE = [acquisisci_fattura_da_file, acquisisci_fattura_da_testo, mostra_bozza,
              elenca_bozze_aperte, modifica_bozza, conferma_bozza, annulla_bozza]


# ===========================================================================
# LEZIONE 6 - DRIVE, EXCEL, COMMERCIALISTA
# ===========================================================================

import archivio
import commercialista


@tool
def esporta_riepilogo_excel(tipo: Literal["mese", "trimestre", "anno"], anno: int, numero: Optional[int] = None) -> str:
    """Crea il file Excel (XLSX) con il riepilogo e l'elenco delle fatture di un periodo, SENZA inviarlo.
    Usalo quando l'utente vuole il file per sé.

    Args:
        tipo: 'mese', 'trimestre' oppure 'anno'.
        anno: anno a 4 cifre, es. 2026.
        numero: numero del mese (1-12) o del trimestre (1-4); non serve se tipo='anno'.
    """
    return f"FILE_CREATO: {commercialista.esporta_riepilogo(tipo, anno, numero)}"


@tool
def invia_riepilogo_al_commercialista(tipo: Literal["mese", "trimestre", "anno"], anno: int,
                                      numero: Optional[int] = None) -> str:
    """Invia via email al commercialista il riepilogo del periodo: file Excel allegato + link privati
    agli originali su Google Drive. È un'azione che NON si può annullare:
    usalo SOLO dopo che l'utente ha confermato esplicitamente periodo e invio.

    Args:
        tipo: 'mese', 'trimestre' oppure 'anno'.
        anno: anno a 4 cifre, es. 2026.
        numero: numero del mese (1-12) o del trimestre (1-4); non serve se tipo='anno'.
    """
    return commercialista.invia_al_commercialista(tipo, anno, numero)


@tool
def riprova_archiviazione() -> str:
    """Riprova a caricare su Google Drive gli originali delle fatture registrate ma non ancora archiviate
    (per esempio perché Drive non era raggiungibile)."""
    return archivio.riprova_archiviazioni()


TOOL_GOOGLE = [esporta_riepilogo_excel, invia_riepilogo_al_commercialista, riprova_archiviazione]

# Tutti i tool dell'assistente .
TOOL_ASSISTENTE = TOOL_BOZZE + TOOL_REGISTRO + TOOL_GOOGLE
