"""
VERIFICA DELLA PARTITA IVA DEI FORNITORI ESTERI sui registri UFFICIALI
=====================================================================

   Paesi UE (anche Irlanda del Nord, XI)  -> VIES della Commissione Europea: gratuito, senza chiave.
                                             Restituisce valida/non valida e, per molti paesi, nome e
                                             indirizzo ufficiali (Germania e Spagna NON li danno).
   Norvegia                               -> Brønnøysund (registro delle imprese): gratuito.
   Regno Unito                            -> HMRC "Check a UK VAT number": gratuito, ma serve registrare
                                             un'applicazione (HMRC_CLIENT_ID e HMRC_CLIENT_SECRET nel .env).
   Altri paesi (USA, Svizzera, Asia...)   -> nessun registro pubblico gratuito interrogabile da programma:
                                             "non verificabile", da controllare a mano (o con un servizio
                                             a pagamento, se l'amministrazione lo decide).

ATTENZIONE: "servizio non disponibile" NON vuol dire "partita IVA non valida". Il VIES risponde
spesso MS_MAX_CONCURRENT_REQ (il paese è sovraccarico): si riprova, e se non va si dice "riprovo più tardi".
"""

import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import httpx

from fatture_comuni import PAESI_UE, PIVA_ESTERO_ASSENTE

log = logging.getLogger(__name__)

URL_VIES = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{paese}/vat/{numero}"
URL_BRREG = "https://data.brreg.no/enhetsregisteret/api/enheter/{numero}"
URL_HMRC_TOKEN = "https://api.service.hmrc.gov.uk/oauth/token"
URL_HMRC = "https://api.service.hmrc.gov.uk/organisations/vat/check-vat-number/lookup/{numero}"

VIES_OCCUPATO = {"MS_MAX_CONCURRENT_REQ", "MS_UNAVAILABLE", "SERVICE_UNAVAILABLE", "TIMEOUT",
                 "GLOBAL_MAX_CONCURRENT_REQ", "SERVER_BUSY"}


def _esito(esito: str, fonte: str, nome: Optional[str] = None, indirizzo: Optional[str] = None,
           nota: Optional[str] = None) -> dict:
    """esito: 'valida' / 'non_valida' / 'non_disponibile' (riprovare) / 'non_verificabile' (a mano)."""
    return {"esito": esito, "fonte": fonte, "nome_ufficiale": nome, "indirizzo_ufficiale": indirizzo,
            "nota": nota, "verificata_il": datetime.now().isoformat(timespec="seconds")}


def _pulisci_testo(testo: Optional[str]) -> Optional[str]:
    if not testo or testo.strip() in ("", "---"):
        return None
    return re.sub(r"\s+", " ", testo.replace("\n", ", ")).strip(" ,")


def _vies(paese: str, numero: str, tentativi: int = 3) -> dict:
    for tentativo in range(tentativi):
        try:
            r = httpx.get(URL_VIES.format(paese=paese, numero=numero), timeout=30)
            r.raise_for_status()
            dati = r.json()
        except Exception as errore:
            log.warning("VIES %s%s: %s", paese, numero, errore)
            dati = {"userError": "TIMEOUT"}
        stato = dati.get("userError", "")
        if stato in VIES_OCCUPATO:
            time.sleep(3 * (tentativo + 1))
            continue
        if dati.get("isValid"):
            return _esito("valida", "VIES", _pulisci_testo(dati.get("name")), _pulisci_testo(dati.get("address")))
        if stato == "INVALID" or dati.get("isValid") is False:
            return _esito("non_valida", "VIES", nota="Il VIES dice che questa partita IVA non è attiva "
                                                     "per le operazioni intracomunitarie.")
        return _esito("non_disponibile", "VIES", nota=f"Risposta VIES: {stato}")
    return _esito("non_disponibile", "VIES", nota="VIES sovraccarico o non raggiungibile: riprovo più tardi.")


def _norvegia(numero: str) -> dict:
    cifre = re.sub(r"\D", "", numero)[:9]
    try:
        r = httpx.get(URL_BRREG.format(numero=cifre), timeout=30)
    except Exception as errore:
        return _esito("non_disponibile", "Brønnøysund", nota=str(errore))
    if r.status_code == 404:
        return _esito("non_valida", "Brønnøysund", nota="Numero non presente nel registro norvegese.")
    if not r.is_success:
        return _esito("non_disponibile", "Brønnøysund", nota=f"HTTP {r.status_code}")
    dati = r.json()
    indirizzo = dati.get("forretningsadresse") or {}
    testo = ", ".join([*indirizzo.get("adresse", []), indirizzo.get("postnummer", ""), indirizzo.get("poststed", "")])
    return _esito("valida", "Brønnøysund", dati.get("navn"), _pulisci_testo(testo))


def _regno_unito(numero: str) -> dict:
    client_id, segreto = os.getenv("HMRC_CLIENT_ID"), os.getenv("HMRC_CLIENT_SECRET")
    if not (client_id and segreto):
        return _esito("non_verificabile", "HMRC", nota="Per la verifica automatica UK serve registrare "
                                                       "un'applicazione gratuita su HMRC Developer Hub.")
    try:
        token = httpx.post(URL_HMRC_TOKEN, data={"grant_type": "client_credentials", "client_id": client_id,
                                                    "client_secret": segreto, "scope": "read:vat"},
                              timeout=30).json()["access_token"]
        r = httpx.get(URL_HMRC.format(numero=re.sub(r"\D", "", numero)), timeout=30,
                         headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/vnd.hmrc.2.0+json"})
    except Exception as errore:
        return _esito("non_disponibile", "HMRC", nota=str(errore))
    if r.status_code == 404:
        return _esito("non_valida", "HMRC", nota="Numero non presente nel registro IVA britannico.")
    if not r.is_success:
        return _esito("non_disponibile", "HMRC", nota=f"HTTP {r.status_code}")
    target = r.json().get("target", {})
    indirizzo = target.get("address", {})
    testo = ", ".join(v for k, v in sorted(indirizzo.items()) if v and k != "countryCode")
    return _esito("valida", "HMRC", target.get("name"), _pulisci_testo(testo))


def verifica(partita_iva: Optional[str], paese: Optional[str]) -> dict:
    """Verifica una partita IVA estera (già normalizzata da fatture_comuni.normalizza_piva)."""
    if not partita_iva or partita_iva == PIVA_ESTERO_ASSENTE:
        return _esito("non_verificabile", "-", nota="Fornitore estero senza partita IVA sulla fattura.")
    prefisso = partita_iva[:2]
    if prefisso == "EU":
        return _esito("non_verificabile", "-", nota="Numero OSS/MOSS (fornitore extra-UE iscritto allo "
                                                    "sportello unico IVA): non è una partita IVA verificabile.")
    if prefisso in PAESI_UE:
        return _vies(prefisso, partita_iva[2:])
    if prefisso == "NO" or paese == "NO":
        return _norvegia(partita_iva)
    if prefisso == "GB" or paese == "GB":
        return _regno_unito(partita_iva)
    return _esito("non_verificabile", "-", nota=f"Nessun registro pubblico gratuito per il paese {paese or '?'}: "
                                                "verifica manuale.")
