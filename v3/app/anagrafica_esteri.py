"""
ANAGRAFICA DEI FORNITORI ESTERI
===============================

Una scheda per ogni fornitore estero, creata da sola alla sua prima fattura registrata:
   - dati DALLA FATTURA: nome, partita IVA, paese, indirizzo (aggiornati a ogni nuova fattura);
   - dati UFFICIALI dal registro del paese (VIES, Brønnøysund, HMRC): esito, nome, indirizzo;
   - STORICO delle modifiche: data, campo, prima, dopo, da dove arriva (fattura o controllo mensile).

Due momenti di controllo:
   1. a OGNI fattura: nome, indirizzo o partita IVA diversi dalla scheda -> avviso + storico;
   2. OGNI MESE (controllo_mensile): si richiedono i dati ufficiali di tutti i fornitori e si
      confrontano con quelli del mese prima -> avviso su Telegram con il prima e il dopo.

I confronti ignorano maiuscole, spazi e punteggiatura ("Rossi S.p.A." = "ROSSI SPA"): conta il contenuto.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import config
import verifica_piva
from fatture_comuni import PIVA_ESTERO_ASSENTE, e_estero

ANAGRAFICA = config.ANAGRAFICA_ESTERI
_verifiche_di_oggi = {}          # stessa partita IVA verificata più volte nello stesso giorno: una sola richiesta


# ---------------------------------------------------------------------------
# FILE
# ---------------------------------------------------------------------------
def carica() -> list:
    return json.loads(ANAGRAFICA.read_text(encoding="utf-8")) if ANAGRAFICA.exists() else []


def _salva(schede: list) -> None:
    if ANAGRAFICA.exists():
        ANAGRAFICA.with_suffix(".bak").write_bytes(ANAGRAFICA.read_bytes())
    temporaneo = ANAGRAFICA.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(schede, ensure_ascii=False, indent=2), encoding="utf-8")
    temporaneo.replace(ANAGRAFICA)


# ---------------------------------------------------------------------------
# AIUTI
# ---------------------------------------------------------------------------
def _parole_di(testo: Optional[str]) -> set:
    """Parole senza accenti, maiuscole e punteggiatura: "Málaga," = "MALAGA"."""
    import unicodedata
    senza_accenti = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[0-9a-z]+", senza_accenti))


def _uguale(a: Optional[str], b: Optional[str], indirizzo: bool = False) -> bool:
    """Stesso contenuto anche se scritto in modo diverso: virgole, accenti, parole ripetute o in altro ordine.
    In prova: "Calle Mayor 10, Planta 2, 29001 Málaga, Spain" e
              "Calle Mayor 10 Planta 2 29001 Málaga Málaga Spain" risultavano "indirizzo cambiato"."""
    attaccato = lambda t: "".join(sorted(_parole_di(t)))
    pa, pb = _parole_di(a), _parole_di(b)
    if indirizzo and pa and pb and (pa <= pb or pb <= pa) and len(pa ^ pb) <= 1:
        return True                    # una sola parola in più, es. "Australia" in fondo all'indirizzo (in prova)
    return pa == pb or re.sub(r"[^0-9a-z]", "", (a or "").lower()) ==         re.sub(r"[^0-9a-z]", "", (b or "").lower()) or attaccato(a) == attaccato(b)


def _chiave(partita_iva: Optional[str], fornitore: Optional[str]) -> str:
    """La partita IVA identifica il fornitore; senza partita IVA (OO999...) si usa il nome."""
    if partita_iva and partita_iva != PIVA_ESTERO_ASSENTE:
        return partita_iva
    return "NOME:" + re.sub(r"[^0-9a-z]", "", (fornitore or "").lower())


def _trova(schede: list, chiave: str) -> Optional[dict]:
    return next((s for s in schede if s["chiave"] == chiave), None)


def _trova_per_nome(schede: list, fornitore: Optional[str]) -> Optional[dict]:
    return next((s for s in schede if _uguale(s["fornitore"], fornitore)), None)


def verifica_oggi(partita_iva: Optional[str], paese: Optional[str]) -> dict:
    chiave = (partita_iva, date.today().isoformat())
    if chiave not in _verifiche_di_oggi or _verifiche_di_oggi[chiave]["esito"] == "non_disponibile":
        _verifiche_di_oggi[chiave] = verifica_piva.verifica(partita_iva, paese)
    return _verifiche_di_oggi[chiave]


def _modifica(scheda: dict, campo: str, prima, dopo, fonte: str) -> str:
    scheda["storico"].append({"data": datetime.now().isoformat(timespec="seconds"), "campo": campo,
                              "prima": prima, "dopo": dopo, "fonte": fonte})
    return f"{scheda['fornitore']}: {campo} cambiato da \"{prima}\" a \"{dopo}\" ({fonte})."


# ---------------------------------------------------------------------------
# 1. CONTROLLI SU UNA FATTURA
# ---------------------------------------------------------------------------
def avvisi_bozza(dati: dict) -> list:
    """Prima di registrare: verifica ufficiale e confronto con la scheda (non salva niente)."""
    if not e_estero(dati.get("paese_fornitore")):
        return []
    avvisi = []
    esito = verifica_oggi(dati.get("partita_iva"), dati.get("paese_fornitore"))
    if esito["esito"] == "non_valida":
        avvisi.append(f"Partita IVA {dati.get('partita_iva')} NON VALIDA secondo {esito['fonte']}: verificala. "
                      f"{esito['nota'] or ''}".strip())
    elif esito["esito"] == "valida" and esito["nome_ufficiale"] and not _uguale(esito["nome_ufficiale"], dati.get("fornitore")):
        avvisi.append(f"Partita IVA valida ({esito['fonte']}), intestata a \"{esito['nome_ufficiale']}\".")
    elif esito["esito"] in ("non_disponibile", "non_verificabile"):
        avvisi.append(f"Partita IVA non verificata: {esito['nota']}")

    schede = carica()
    scheda = _trova(schede, _chiave(dati.get("partita_iva"), dati.get("fornitore")))
    if scheda is None:
        stesso_nome = _trova_per_nome(schede, dati.get("fornitore"))
        if stesso_nome:
            avvisi.append(f"ANAGRAFICA: {stesso_nome['fornitore']} aveva la partita IVA {stesso_nome['partita_iva']}, "
                          f"questa fattura riporta {dati.get('partita_iva')}.")
        else:
            avvisi.append("Nuovo fornitore estero: alla registrazione creo la scheda in anagrafica.")
        return avvisi
    if not _uguale(scheda["fornitore"], dati.get("fornitore")):
        avvisi.append(f"ANAGRAFICA: nome diverso dalla scheda (\"{scheda['fornitore']}\").")
    if dati.get("indirizzo_fornitore") and not _uguale(scheda["indirizzo"], dati["indirizzo_fornitore"], indirizzo=True):
        avvisi.append(f"ANAGRAFICA: indirizzo diverso dalla scheda (\"{scheda['indirizzo']}\").")
    return avvisi


def _riferimento(fattura: dict) -> str:
    """Identità della FATTURA (numero + data), per riconoscerla se viene elaborata di nuovo."""
    return f"{re.sub(r'[^0-9a-z]', '', (fattura.get('numero') or '').lower())}|{fattura.get('data_emissione') or ''}"


def _solo_cifre(partita_iva: Optional[str]) -> str:
    return re.sub(r"^[A-Z]{2}", "", (partita_iva or "").upper())


def aggiorna_da_fattura(fattura: dict) -> list:
    """Dopo la registrazione: crea o aggiorna la scheda del fornitore. Restituisce gli avvisi.
    Una fattura già vista non produce modifiche: rielaborare un mese non deve creare note false
    (in prova: Adatum riletta più volte, il paese letto prima HK e poi IE, "partita IVA cambiata")."""
    if not e_estero(fattura.get("paese_fornitore")):
        return []
    schede = carica()
    rif = _riferimento(fattura)
    if any(rif in s.get("riferimenti", []) for s in schede):
        return []
    chiave = _chiave(fattura.get("partita_iva"), fattura.get("fornitore"))
    scheda = _trova(schede, chiave)
    fonte = f"fattura {fattura['id']} del {fattura['data_emissione']}"
    avvisi = []

    if scheda is None:
        stesso_nome = _trova_per_nome(schede, fattura.get("fornitore"))
        if stesso_nome and fattura.get("partita_iva") == PIVA_ESTERO_ASSENTE and                 stesso_nome["partita_iva"] != PIVA_ESTERO_ASSENTE:
            # la fattura non la riporta (o non è stata letta), ma il fornitore la ha già: non è un cambio
            scheda = stesso_nome
            avvisi.append(f"{scheda['fornitore']}: partita IVA non trovata sulla fattura, in anagrafica è "
                          f"{scheda['partita_iva']}: da controllare.")
        elif stesso_nome and "EU" in ((stesso_nome["partita_iva"] or "")[:2], (fattura.get("partita_iva") or "")[:2]):
            # in prova (Litware): la fattura riporta sia "VAT GB 123456782" sia il numero OSS "EU372000025"
            scheda = stesso_nome
            avvisi.append(f"{scheda['fornitore']}: ha sia la partita IVA {scheda['partita_iva']} sia il numero "
                          f"{fattura.get('partita_iva')}: da controllare quale usare.")
        elif stesso_nome and _solo_cifre(stesso_nome["partita_iva"]) == _solo_cifre(fattura.get("partita_iva")):
            # stesse cifre, cambia solo il prefisso del paese: è una lettura diversa, non un cambio
            scheda = stesso_nome
            avvisi.append(f"{scheda['fornitore']}: paese della partita IVA da controllare "
                          f"({scheda['partita_iva']} o {fattura.get('partita_iva')}).")
        elif stesso_nome:                                       # stesso fornitore, partita IVA cambiata
            scheda = stesso_nome
            avvisi.append(_modifica(scheda, "partita IVA", scheda["partita_iva"], fattura.get("partita_iva"), fonte))
            scheda["chiave"], scheda["partita_iva"] = chiave, fattura.get("partita_iva")
        else:
            esito = verifica_oggi(fattura.get("partita_iva"), fattura.get("paese_fornitore"))
            scheda = {"chiave": chiave, "fornitore": fattura["fornitore"], "partita_iva": fattura.get("partita_iva"),
                      "paese": fattura.get("paese_fornitore"), "indirizzo": fattura.get("indirizzo_fornitore"),
                      "ufficiale": esito, "prima_fattura": fattura["data_emissione"], "fatture": [], "storico": []}
            schede.append(scheda)
            avvisi.append(f"Creata la scheda anagrafica di {fattura['fornitore']} "
                          f"(verifica partita IVA: {esito['esito'].replace('_', ' ')}).")
    else:
        if not _uguale(scheda["fornitore"], fattura["fornitore"]):
            avvisi.append(_modifica(scheda, "nome", scheda["fornitore"], fattura["fornitore"], fonte))
            scheda["fornitore"] = fattura["fornitore"]
        if fattura.get("indirizzo_fornitore") and not _uguale(scheda["indirizzo"], fattura["indirizzo_fornitore"], indirizzo=True):
            avvisi.append(_modifica(scheda, "indirizzo", scheda["indirizzo"], fattura["indirizzo_fornitore"], fonte))
            scheda["indirizzo"] = fattura["indirizzo_fornitore"]
    scheda["fatture"].append(fattura["id"])
    scheda.setdefault("riferimenti", []).append(rif)
    scheda["ultima_fattura"] = fattura["data_emissione"]
    _salva(schede)
    return avvisi


# ---------------------------------------------------------------------------
# 2. CONTROLLO MENSILE sui registri ufficiali
# ---------------------------------------------------------------------------
def controllo_mensile() -> str:
    schede = carica()
    if not schede:
        return "Anagrafica fornitori esteri vuota: nessun controllo da fare."
    modifiche, da_riprovare, a_mano = [], [], []
    fonte = f"controllo mensile del {date.today():%d/%m/%Y}"
    for s in schede:
        nuovo = verifica_piva.verifica(s["partita_iva"], s["paese"])
        vecchio = s.get("ufficiale") or {}
        if nuovo["esito"] == "non_disponibile":
            da_riprovare.append(s["fornitore"])
            continue                                  # niente confronto: non sappiamo, non è un cambiamento
        if nuovo["esito"] == "non_verificabile":
            a_mano.append(f"{s['fornitore']} ({s['paese']})")
        elif vecchio.get("esito") and nuovo["esito"] != vecchio["esito"]:
            modifiche.append(_modifica(s, "esito verifica partita IVA", vecchio["esito"], nuovo["esito"], fonte))
        for campo, chiave in (("nome ufficiale", "nome_ufficiale"), ("indirizzo ufficiale", "indirizzo_ufficiale")):
            if vecchio.get(chiave) and nuovo.get(chiave) and not _uguale(vecchio[chiave], nuovo[chiave], indirizzo=chiave == "indirizzo_ufficiale"):
                modifiche.append(_modifica(s, campo, vecchio[chiave], nuovo[chiave], fonte))
        s["ufficiale"] = nuovo
    _salva(schede)

    righe = [f"Controllo anagrafica fornitori esteri ({len(schede)} fornitori)."]
    righe += ["MODIFICHE:", *[f"- {m}" for m in modifiche]] if modifiche else ["Nessuna modifica rispetto al mese scorso."]
    if da_riprovare:
        righe.append(f"Registro non raggiungibile, da riprovare: {', '.join(da_riprovare)}.")
    if a_mano:
        righe.append(f"Da verificare a mano (nessun registro pubblico): {', '.join(a_mano)}.")
    return "\n".join(righe)


def esporta_excel() -> Path:
    """Anagrafica + storico delle modifiche in un file Excel (due fogli)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    schede = carica()
    righe = [{"Fornitore": s["fornitore"], "Partita IVA": s["partita_iva"], "Paese": s["paese"],
              "Indirizzo (fattura)": s["indirizzo"],
              "Verifica": (s.get("ufficiale") or {}).get("esito"), "Fonte": (s.get("ufficiale") or {}).get("fonte"),
              "Nome ufficiale": (s.get("ufficiale") or {}).get("nome_ufficiale"),
              "Indirizzo ufficiale": (s.get("ufficiale") or {}).get("indirizzo_ufficiale"),
              "Verificata il": (s.get("ufficiale") or {}).get("verificata_il"),
              "Prima fattura": s["prima_fattura"], "Ultima fattura": s.get("ultima_fattura"),
              "N. fatture": len(s["fatture"])} for s in schede]
    storico = [{"Fornitore": s["fornitore"], "Data": m["data"], "Campo": m["campo"], "Prima": m["prima"],
                "Dopo": m["dopo"], "Fonte": m["fonte"]} for s in schede for m in s["storico"]]
    percorso = config.RIEPILOGHI / f"anagrafica_fornitori_esteri_{date.today():%Y%m%d}.xlsx"
    libro = Workbook()
    for foglio, titolo, dati, colonne in (
            (libro.active, "Anagrafica", righe, list(righe[0]) if righe else ["Fornitore"]),
            (libro.create_sheet(), "Storico modifiche", storico, ["Fornitore", "Data", "Campo", "Prima", "Dopo", "Fonte"])):
        foglio.title = titolo
        foglio.append(colonne)
        for cella in foglio[1]:
            cella.font = Font(bold=True)
        for riga in dati:
            foglio.append([riga.get(c) for c in colonne])
        for colonna in foglio.columns:
            foglio.column_dimensions[colonna[0].column_letter].width = min(
                60, max(12, *(len(str(c.value or "")) + 2 for c in colonna)))
    libro.save(percorso)
    return percorso
