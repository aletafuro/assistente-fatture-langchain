"""
PEZZI COMUNI: schema dei dati della fattura, conversioni e controlli.

Principio del progetto: L'LLM LEGGE, PYTHON CONVERTE E CONTA.
L'LLM copia importi e date COME SONO SCRITTI ("1.200,00", "12/03/2025", "22 settembre 2026");
Python li converte in centesimi interi e in date AAAA-MM-GG e fa tutti i controlli.
"""

import json
import logging
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pypdf import PdfReader

import config

GOLDEN_SET = config.GOLDEN_SET

CAMPI_CONFRONTO = ["fornitore", "partita_iva", "numero", "data_emissione", "data_scadenza",
                   "imponibile_cent", "iva_cent", "totale_cent", "regime_iva"]

# La nostra azienda è SEMPRE il cliente: in una fattura estera impaginata a colonne il primo nome
# in alto era il nostro, e il fornitore non veniva riconosciuto. Nome e P.IVA arrivano dal .env.
AZIENDA = config.AZIENDA_NOME
_CLIENTE = (f"Il cliente è sempre {AZIENDA}" + (f" (partita IVA IT{config.AZIENDA_PIVA})" if config.AZIENDA_PIVA else "")
            + f": {AZIENDA} e la sua partita IVA non sono MAI quelli del fornitore. ") if AZIENDA else ""

ISTRUZIONI_ESTRAZIONE = (
    "Sei un assistente contabile italiano. Estrai i dati dalla fattura che ti viene fornita: "
    "può essere italiana o estera, in qualsiasi lingua. "
    "Attenzione: nelle fatture compare sia il fornitore (chi emette) sia il cliente (chi riceve): "
    "i campi fornitore, partita_iva, paese_fornitore e indirizzo_fornitore riguardano SOLO il fornitore. "
    f"{_CLIENTE}"
    "Nelle fatture in inglese il fornitore è chi emette la 'Invoice'; il cliente è in 'Bill to', 'Customer', "
    "'Sold to'. La partita IVA del fornitore può essere in alto, nell'intestazione, ma spesso è nel PIÈ DI "
    "PAGINA ('VAT REG', 'VAT number', 'Tax ID', 'USt-IdNr', 'TVA'): cercala in tutto il documento, fino in fondo. "
    "Un fornitore extra-UE può avere una partita IVA europea (di un suo rappresentante in Europa): usa quella. "
    "Non inventare mai: se un dato non è presente, lascialo vuoto."
)


class DatiFattura(BaseModel):
    """Dati principali di una fattura ricevuta da un fornitore."""

    fornitore: Optional[str] = Field(
        default=None,
        description="Ragione sociale di chi EMETTE la fattura (il fornitore). NON il cliente/destinatario.")
    partita_iva: Optional[str] = Field(
        default=None,
        description="Partita IVA / VAT number / Tax ID del FORNITORE, copiata ESATTAMENTE come scritta, "
                    "con l'eventuale prefisso del paese (es. 'IT01234567890', 'NL.817154243.B.01', "
                    "'GB123456789'). Mai quella del cliente.")
    paese_fornitore: Optional[str] = Field(
        default=None,
        description="Paese del FORNITORE come codice ISO di 2 lettere (IT, NL, IE, DE, FR, GB, US, CH...), "
                    "dedotto dall'INDIRIZZO della sede del fornitore. Attenzione: una società estera può avere "
                    "una partita IVA italiana o europea (es. una compagnia aerea inglese con P.IVA IT): "
                    "il paese resta quello dell'indirizzo, non quello della partita IVA.")
    indirizzo_fornitore: Optional[str] = Field(
        default=None,
        description="Indirizzo del FORNITORE su una riga (via, CAP, città, paese), copiato come scritto.")
    valuta: Optional[str] = Field(
        default=None,
        description="Valuta degli importi come codice ISO di 3 lettere (EUR, USD, GBP, CHF...). "
                    "€ = EUR, $ = USD (salvo indicazione diversa), £ = GBP. Copia il codice che vedi sulla "
                    "fattura (es. 'CSK' o 'Kč' per le corone ceche): non sostituirlo con un'altra valuta.")
    numero: Optional[str] = Field(
        default=None,
        description="Numero della fattura, copiato esattamente come scritto (es. '2026/037').")
    data_emissione: Optional[str] = Field(
        default=None,
        description="Data di emissione copiata ESATTAMENTE come scritta, senza cambiarne il formato "
                    "(es. '12/03/2025' oppure '2026-06-10'). È la data del DOCUMENTO, scritta come 'Data', 'Date', "
                    "'Invoice date', 'Date of issue', 'Issued' oppure, in una ricevuta ('Receipt'), 'Date paid' / "
                    "'Payment date'. Lascia vuoto solo se il documento non ha nessuna di queste date "
                    "(la data di scadenza e le date del periodo non valgono).")
    fine_periodo: Optional[str] = Field(
        default=None,
        description="Se la fattura indica un periodo di fatturazione (es. 'billing period August 1, 2026 - "
                    "September 1, 2026'), la data di FINE periodo copiata come scritta. Altrimenti vuoto.")
    data_scadenza: Optional[str] = Field(
        default=None,
        description="Data di scadenza del pagamento copiata ESATTAMENTE come scritta. "
                    "Se non c'è una data scritta esplicitamente, lascia vuoto: non calcolarla.")
    imponibile: Optional[str] = Field(
        default=None,
        description="Imponibile copiato come scritto sulla fattura, es. '1.200,00' o '1,200.00'. "
                    "Senza simbolo di valuta.")
    iva: Optional[str] = Field(
        default=None,
        description="Importo dell'IVA copiato come scritto, es. '264,00'. Senza simbolo di valuta.")
    totale: Optional[str] = Field(
        default=None,
        description="Totale documento (IVA inclusa) copiato come scritto, es. '1.464,00'. "
                    "Non l'eventuale 'importo dovuto' al netto di trattenute. Senza simbolo di valuta.")
    tipo_documento: Literal["fattura", "nota_di_credito", "proforma", "altro"] = Field(
        default="fattura",
        description="'fattura' (anche 'Invoice', 'Receipt' di un acquisto); 'nota_di_credito' se è una nota di "
                    "credito / credit note / rimborso; 'proforma' se è una fattura pro-forma / proforma invoice "
                    "(richiesta di pagamento prima della fattura vera); 'altro' se NON è una fattura (contabile di "
                    "bonifico, avviso di parcella, preventivo, guida, estratto conto).")
    metodo_pagamento: Optional[str] = Field(
        default=None,
        description="Come è stata pagata, se è scritto: es. 'American Express 2007', 'Visa 1234', "
                    "'Mastercard 3978', 'bonifico', 'PayPal'. Con le ultime cifre della carta se ci sono.")
    regime_iva: Literal["ordinario", "inversione_contabile", "aliquota_ridotta", "esente"] = Field(
        description="'ordinario' se IVA al 22%; 'inversione_contabile' se reverse charge; "
                    "'aliquota_ridotta' se IVA al 4%, 5% o 10%; 'esente' se esente/non imponibile.")


logging.getLogger("pypdf").setLevel(logging.ERROR)   # niente messaggi tecnici di pypdf a video


# ---------------------------------------------------------------------------
# FATTURE ELETTRONICHE ITALIANE (formato ministeriale SDI)
# ---------------------------------------------------------------------------
def formato_sdi(testo: str) -> bool:
    """Le fatture italiane stampate dallo SDI hanno sempre queste due sezioni; quelle estere mai."""
    return "Cedente/prestatore" in testo and "Cessionario/committente" in testo


def scadenze_sdi(testo: str) -> list:
    """
    Dalla sezione 'Scadenze' del formato SDI. Due casi:
      'Data scadenza 30-11-2026'            -> 2026-11-30
      'Data termine 15-09-2026 46gg'        -> 15/09 + 46 giorni = 2026-10-31
    (la seconda forma l'abbiamo vista su una fattura vera: il modello avrebbe preso il 15/09 come scadenza).
    """
    from datetime import timedelta
    risultato = []
    for data, giorni in re.findall(r"Data (?:termine|scadenza)\s+(\d{2}[-/]\d{2}[-/]\d{4})(?:\s+(\d+)\s*gg)?", testo):
        base = datetime.strptime(data.replace("/", "-"), "%d-%m-%Y")
        risultato.append((base + timedelta(days=int(giorni or 0))).strftime("%Y-%m-%d"))
    return risultato


def pulisci_testo_pdf(testo: str) -> str:
    """Alcuni PDF (es. le fatture generate da Stripe) codificano il trattino con un carattere nullo:
    "9BF0758D-5703622" esce come "9BF0758D\\x005703622" e il modello lo scartava, perdendo il trattino."""
    testo = re.sub(r"(?<=\w)\x00(?=\w)", "-", testo)
    return testo.replace("\x00", "")


def leggi_pdf(percorso: Path) -> str:
    lettore = PdfReader(percorso)
    return pulisci_testo_pdf("\n".join(pagina.extract_text() or "" for pagina in lettore.pages))


def euro_in_centesimi(testo: Optional[str]) -> Optional[int]:
    if testo is None:
        return None
    # Si tengono solo cifre, separatori e segno: via valute, simboli e altro testo ("0%", "99.00 USD", "Kč")
    senza_percentuali = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", testo)
    pulito = re.sub(r"[^0-9.,\-]", "", senza_percentuali)
    if not re.search(r"\d", pulito):
        return 0 if "%" in testo else None
    cifre = pulito.lstrip("-")
    if "," in cifre and "." in cifre:
        # Ci sono entrambi: il separatore dei DECIMALI è l'ultimo che compare.
        # "1.200,00" (italiano) oppure "1,200.00" (inglese, fatture estere).
        if cifre.rfind(",") > cifre.rfind("."):
            pulito = pulito.replace(".", "").replace(",", ".")
        else:
            pulito = pulito.replace(",", "")
    elif "," in cifre:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", cifre):
            pulito = pulito.replace(",", "")          # "1,500" inglese: migliaia
        else:
            pulito = pulito.replace(",", ".")         # "264,00" italiano: decimali
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", cifre):
        # "6.100" o "1.500.000" senza virgola: il punto separa le MIGLIAIA, non i decimali
        # (prima "6.100 euro" veniva letto come 6,10 €).
        pulito = pulito.replace(".", "")
    return int((Decimal(pulito) * 100).to_integral_value(ROUND_HALF_UP))


def vuoto_se_niente(testo: Optional[str]) -> Optional[str]:
    """A volte l'LLM risponde '' (stringa vuota) invece di lasciare vuoto: per noi è la stessa cosa."""
    if testo is None or testo.strip() == "":
        return None
    return testo.strip()


MESI_ITALIANI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
                 "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}

# Fatture estere: nomi dei mesi in inglese (es. "1 September 2026"),
# francese, tedesco, spagnolo, olandese. Bastano le prime 3 lettere ("Sep", "Sept", "September").
_MESI = [
    ("gen", "jan", "janv", "ene", "jän"), ("feb", "fév", "fev"), ("mar", "mär", "maa", "mrt"),
    ("apr", "avr", "abr"), ("mag", "may", "mai", "mei"), ("giu", "jun", "juin"),
    ("lug", "jul", "juil"), ("ago", "aug", "aoû", "aou"), ("set", "sep"), ("ott", "oct", "okt"),
    ("nov",), ("dic", "dec", "déc", "dez", "dic"),
]


def _numero_mese(parola: str) -> Optional[int]:
    parola = parola.lower().strip(".")
    if parola in MESI_ITALIANI:
        return MESI_ITALIANI[parola]
    for numero, prefissi in enumerate(_MESI, start=1):
        if any(parola.startswith(p) for p in prefissi) and len(parola) >= 3:
            return numero
    return None


def normalizza_data(testo: Optional[str], paese: Optional[str] = None) -> Optional[str]:
    """Da '12/03/2025', '2025-03-12', '12 marzo 2025', '1 September 2026', 'Sep 1, 2026'
    sempre a '2025-03-12' (formato AAAA-MM-GG).
    paese='US': le date con le barre sono mese/giorno/anno (09/01/2026 = 1 settembre)."""
    testo = vuoto_se_niente(testo)
    if testo is None:
        return None
    # Date a parole: "22 settembre 2026", "1 September 2026", "September 1, 2026", "01-Sep-2026", "1st Sep 2026"
    parole = [p.strip(".") for p in
              re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", testo.lower().replace(",", " ").replace("-", " ")).split()]
    # Si convertono direttamente in AAAA-MM-GG: la regola americana (mese/giorno) vale solo per le date
    # scritte con le cifre. Prima "21 settembre 2026" di un fornitore USA diventava 21/9 e poi "mese 21".
    if len(parole) == 3 and parole[2].isdigit():
        giorno_mese = None
        if _numero_mese(parole[1]) and parole[0].isdigit():          # giorno mese anno
            giorno_mese = (int(parole[0]), _numero_mese(parole[1]))
        elif _numero_mese(parole[0]) and parole[1].isdigit():        # mese giorno anno (inglese)
            giorno_mese = (int(parole[1]), _numero_mese(parole[0]))
        if giorno_mese:
            try:
                return date(int(parole[2]), giorno_mese[1], giorno_mese[0]).isoformat()
            except ValueError:
                return None
    formati = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"]
    if (paese or "").upper() == "US" and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", testo):
        formati = ["%m/%d/%Y", "%m/%d/%y"]
    for formato in formati:
        try:
            return datetime.strptime(testo, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # "09/30/2026": il 30 non può essere un mese, quindi è per forza mese/giorno (data all'americana)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", testo)
    if m and int(m.group(2)) > 12 >= int(m.group(1)):
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    return None   # formato sconosciuto: meglio vuoto (e chiederlo) che sbagliato


# ---------------------------------------------------------------------------
# PARTITA IVA ITALIANA ED ESTERA
# ---------------------------------------------------------------------------
# Codice convenzionale per un fornitore ESTERO senza partita IVA sulla fattura (regola dell'amministrazione,
# come nell'esterometro): "OO" + undici volte 9.
PIVA_ESTERO_ASSENTE = "OO99999999999"

# Paesi UE: la partita IVA si verifica sul VIES. La Grecia nel VIES usa "EL", l'Irlanda del Nord "XI".
PAESI_UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE",
            "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI"}
# Paesi extra-UE che scrivono di solito il prefisso del paese davanti al numero
PAESI_CON_PREFISSO = {"GB", "CH", "NO", "CHE"}


def normalizza_paese(paese: Optional[str]) -> Optional[str]:
    paese = (vuoto_se_niente(paese) or "").upper()
    if paese == "GR":
        return "EL"
    if paese == "UK":
        return "GB"
    return paese if re.fullmatch(r"[A-Z]{2}", paese) else None


def e_estero(paese: Optional[str]) -> bool:
    paese = normalizza_paese(paese)
    return paese is not None and paese != "IT"


def normalizza_piva(testo: Optional[str], paese: Optional[str] = None) -> tuple:
    """
    Python (non l'LLM) mette in forma la partita IVA. Restituisce (partita_iva, paese).
      'IT 01234567890' / '01234567890'  -> ('01234567890', 'IT')     italiana: solo le 11 cifre
      'NL.817154243.B.01'               -> ('NL123456789B01', 'NL')  estera: prefisso + codice, senza punti
      vuota e fornitore estero          -> ('OO99999999999', paese)
    """
    paese = normalizza_paese(paese)
    pulita = re.sub(r"[\s.\-/:]", "", vuoto_se_niente(testo) or "").upper()
    # Etichette che a volte vengono copiate insieme al numero ("VAT REG", "EIN", "ABN", "Tax ID"...)
    pulita = re.sub(r"^(VATREG|VATNO|VATNUMBER|VAT|TAXID|EIN|ABN|GST|UIDNR|UID|MWST|USTIDNR|TVA|BTW|NIF|CIF|PIVA)",
                    "", pulita)
    if config.AZIENDA_PIVA and pulita.removeprefix("IT") == config.AZIENDA_PIVA:
        pulita = ""                                # è la NOSTRA partita IVA (cliente): non è del fornitore
    if pulita == PIVA_ESTERO_ASSENTE or re.fullmatch(r"EU\d+", pulita):
        return pulita, paese                       # "EU372000017" = numero OSS/MOSS di un fornitore extra-UE
    prefisso = normalizza_paese(pulita[:2]) if re.match(r"[A-Z]{2}", pulita) else None
    if prefisso and prefisso not in PAESI_UE | PAESI_CON_PREFISSO and prefisso != paese:
        prefisso = None                            # due lettere che non sono un paese: fanno parte del codice
    if prefisso:
        paese = paese or prefisso
    if not pulita:
        return (PIVA_ESTERO_ASSENTE if e_estero(paese) else None), paese
    if prefisso == "IT" or (prefisso is None and paese in (None, "IT") and re.fullmatch(r"\d{11}", pulita)):
        return pulita.removeprefix("IT"), "IT"
    if prefisso is None and paese:
        return f"{paese}{pulita}", paese
    if prefisso and prefisso != pulita[:2]:        # GR -> EL
        pulita = prefisso + pulita[2:]
    return pulita, paese


def piva_italiana_valida(piva: str) -> bool:
    """11 cifre e cifra di controllo corretta (algoritmo ufficiale dell'Agenzia delle Entrate)."""
    if not re.fullmatch(r"\d{11}", piva or ""):
        return False
    somma = 0
    for i, c in enumerate(piva[:10]):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        somma += n
    return (10 - somma % 10) % 10 == int(piva[10])


def controlla_coerenza(imponibile_cent, iva_cent, totale_cent) -> bool:
    """Controllo contabile: imponibile + IVA deve fare esattamente il totale."""
    if None in (imponibile_cent, iva_cent, totale_cent):
        return False
    return imponibile_cent + iva_cent == totale_cent


def _per_forza_americana(testo: Optional[str]) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", testo or "")
    return bool(m) and int(m.group(2)) > 12 >= int(m.group(1))


def pulisci_numero(testo: Optional[str]) -> Optional[str]:
    """'1 - 09/08/2026' -> '1': a volte il modello attacca la data al numero della fattura."""
    testo = vuoto_se_niente(testo)
    if testo is None:
        return None
    return re.sub(r"\s*[-–]\s*\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\s*$", "", testo).strip() or None


def normalizza_valuta(testo: Optional[str]) -> Optional[str]:
    testo = (vuoto_se_niente(testo) or "").upper()
    testo = {"€": "EUR", "$": "USD", "£": "GBP", "EURO": "EUR", "DOLLARI": "USD", "STERLINE": "GBP",
             "CSK": "CZK", "KČ": "CZK", "KC": "CZK", "ZŁ": "PLN", "FR.": "CHF"}.get(testo, testo)
    return testo if re.fullmatch(r"[A-Z]{3}", testo) else None


def in_dizionario(nome_file: str, dati: DatiFattura) -> dict:
    """Trasforma quello che ha letto l'LLM in un dizionario con gli importi in centesimi.
    Gli importi restano nella VALUTA DELLA FATTURA: la conversione in euro (cambio BdI del giorno
    della fattura) la fa Python dopo, in cambi_bdi.py."""
    partita_iva, paese = normalizza_piva(dati.partita_iva, dati.paese_fornitore)
    # Se una data della fattura è per forza all'americana ("09/30/2026"), lo sono tutte: altrimenti
    # la scadenza "10/07/2026" (7 ottobre) diventava il 10 luglio, prima della data della fattura.
    formato_date = "US" if any(_per_forza_americana(d) for d in (dati.data_emissione, dati.data_scadenza,
                                                                  dati.fine_periodo)) else paese
    valuta = normalizza_valuta(dati.valuta)
    if valuta is None and paese == "IT":
        valuta = "EUR"
    return {
        "_grezzo": dati.model_dump(),      # risposta del modello così com'è (si salva per non richiederla)
        "file": nome_file,
        # "Rossi S.p.A ." -> "Rossi S.p.A.": il PDF a volte lascia spazi prima della punteggiatura
        "fornitore": re.sub(r"\s+([.,])", r"\1", vuoto_se_niente(dati.fornitore) or "") or None,
        "partita_iva": partita_iva,
        "paese_fornitore": paese,
        "indirizzo_fornitore": vuoto_se_niente(dati.indirizzo_fornitore),
        "numero": pulisci_numero(dati.numero),
        "data_emissione": normalizza_data(dati.data_emissione, formato_date),
        "fine_periodo": normalizza_data(dati.fine_periodo, formato_date),
        "data_scadenza": normalizza_data(dati.data_scadenza, formato_date),
        "valuta": valuta,
        "imponibile_cent": euro_in_centesimi(vuoto_se_niente(dati.imponibile)),
        "iva_cent": euro_in_centesimi(vuoto_se_niente(dati.iva)),
        "totale_cent": euro_in_centesimi(vuoto_se_niente(dati.totale)),
        "regime_iva": dati.regime_iva,
        "tipo_documento": dati.tipo_documento,
        "metodo_pagamento": vuoto_se_niente(dati.metodo_pagamento),
    }


def carica_golden_set() -> dict:
    return {riga["file"]: riga for riga in json.load(open(GOLDEN_SET, encoding="utf-8"))}


def _per_confronto(campo: str, valore) -> str:
    testo = str(valore).strip().lower()
    if campo == "fornitore":
        # "Cartoleria Bianchi S.r.l." e "Cartoleria Bianchi SRL" sono lo stesso fornitore:
        # la punteggiatura della forma societaria non conta, le lettere sì ("Cartoneria" resta un errore).
        testo = "".join(c for c in testo if c.isalnum())
    return testo


def campi_sbagliati(estratto: dict, atteso: dict) -> list:
    return [c for c in CAMPI_CONFRONTO
            if _per_confronto(c, estratto[c]) != _per_confronto(c, atteso[c])]
