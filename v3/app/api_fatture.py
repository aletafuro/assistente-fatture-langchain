"""
API REST DEL REGISTRO FATTURE (v3) - SOLA LETTURA
=================================================

Il bot è fatto per le PERSONE (chat). Questa API è fatta per gli ALTRI PROGRAMMI: un gestionale,
un foglio di calcolo, una dashboard, uno script che ogni mattina scarica le scadenze.
Risponde in JSON, con campi sempre uguali e documentati.

Stessa scelta di sicurezza del server MCP (server_mcp.py): SOLO LETTURA.
Cercare, riassumere, scadenze. Registrare, pagare e annullare restano nella chat, dove c'è
sempre una persona che conferma.

Chi chiama deve mandare la chiave API_CHIAVE (dal .env) nell'header X-API-Key.
Senza chiave configurata l'API risponde solo a /salute.

Avvio (dalla cartella v3):   uv run uvicorn api_fatture:app --app-dir app --port 8000
Documentazione interattiva:  http://127.0.0.1:8000/docs  (si provano le chiamate dal browser)

Gli importi sono in CENTESIMI INTERI come nel registro (12345 = 123,45 €): niente arrotondamenti.
"""

import secrets
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

import config
import registro_fatture as reg
import scadenziario

app = FastAPI(
    title="Registro fatture fornitori",
    version="3.1",
    description="API di sola lettura sul registro delle fatture e sullo scadenziario. "
                "Importi in centesimi interi. Autenticazione: header X-API-Key.",
)


# ---------------------------------------------------------------------------
# LA CHIAVE
# ---------------------------------------------------------------------------

intestazione_chiave = APIKeyHeader(name="X-API-Key", auto_error=False)


def controlla_chiave(chiave: Optional[str] = Security(intestazione_chiave)) -> None:
    """Gira prima di ogni chiamata protetta: se la chiave manca o è sbagliata, la richiesta si ferma qui."""
    if not config.API_CHIAVE:
        raise HTTPException(503, "API non configurata: manca API_CHIAVE nel file .env.")
    # compare_digest confronta in tempo costante: dal tempo di risposta non si indovina la chiave.
    if not chiave or not secrets.compare_digest(chiave, config.API_CHIAVE):
        raise HTTPException(401, "Chiave mancante o non valida (header X-API-Key).")


@app.exception_handler(reg.ErroreRegistro)
def registro_danneggiato(request, errore: reg.ErroreRegistro):
    return JSONResponse(status_code=503, content={"detail": str(errore)})


# ---------------------------------------------------------------------------
# LA FORMA DELLE RISPOSTE (Pydantic): sono anche la documentazione di /docs
# ---------------------------------------------------------------------------

class Fattura(BaseModel):
    # Solo i campi utili a chi legge: i percorsi dei file sul server e i link di Drive restano fuori.
    id: str
    fornitore: str
    partita_iva: Optional[str] = None
    paese_fornitore: str = "IT"
    numero: str
    data_emissione: date
    data_scadenza: Optional[date] = None
    imponibile_cent: Optional[int] = None
    iva_cent: Optional[int] = None
    totale_cent: Optional[int] = None
    valuta: str = "EUR"
    totale_valuta_cent: Optional[int] = None
    cambio_bdi: Optional[float] = None
    regime_iva: str = "ordinario"
    stato_pagamento: str
    data_pagamento: Optional[date] = None
    annullata: bool
    motivo_annullamento: Optional[str] = None
    avvisi: list[str] = []


class Scadenza(BaseModel):
    fattura: Fattura
    giorni_alla_scadenza: int           # negativo = già scaduta
    scaduta: bool


class Riepilogo(BaseModel):
    tipo: str
    anno: int
    numero: Optional[int] = None
    numero_fatture: int
    imponibile_cent: int
    iva_cent: int
    totale_cent: int
    da_pagare_cent: int
    per_fornitore_cent: dict[str, int]  # dal fornitore più costoso
    iva_da_verificare: list[str]        # id delle fatture con regime IVA non ordinario


class RigaScadenziario(BaseModel):
    # Le righe dello scadenziario Excel (anche quelle scritte a mano dall'amministrazione).
    fornitore: Optional[str] = None
    numero_fattura: Optional[str] = None
    data_fattura: Optional[date] = None
    importo_valuta: Optional[float] = None
    valuta: Optional[str] = None
    importo_euro: Optional[float] = None
    termini_di_pagamento: Optional[str] = None
    data_di_scadenza: Optional[date] = None
    rata: Optional[str] = None
    stato: Optional[str] = None
    note: Optional[str] = None


def _riga_scadenziario(r: dict) -> RigaScadenziario:
    def numero(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):     # importo scritto a mano come testo: meglio vuoto che un errore
            return None

    def testo(v):
        return None if v in (None, "") else str(v)

    def giorno(v):
        v = scadenziario._giorno(v)
        return v if isinstance(v, date) else None
    return RigaScadenziario(
        fornitore=testo(r["Fornitore"]), numero_fattura=testo(r["Numero Fattura"]),
        data_fattura=giorno(r["Data Fattura"]), importo_valuta=numero(r["Importo Valuta Originaria"]),
        valuta=testo(r["Valuta"]), importo_euro=numero(r["Importo EURO"]),
        termini_di_pagamento=testo(r["Termini di Pagamento"]), data_di_scadenza=giorno(r["Data di Scadenza"]),
        rata=testo(r["Rata"]), stato=testo(r["Stato"]), note=testo(r["Note"]))


# ---------------------------------------------------------------------------
# LE CHIAMATE
# ---------------------------------------------------------------------------

@app.get("/salute", tags=["servizio"])
def salute() -> dict:
    """Il servizio è acceso? Non serve la chiave e non mostra dati (lo usa il controllo del container)."""
    return {"stato": "ok"}


protette = APIRouter(dependencies=[Depends(controlla_chiave)])


@protette.get("/fatture", tags=["registro"])
def elenco_fatture(
    testo: str = Query("", description="Parole da cercare in fornitore, numero, id o partita IVA"),
    stato: Literal["tutte", "da_pagare", "pagata", "annullata"] = "tutte",
) -> list[Fattura]:
    """Cerca nel registro, come la ricerca della chat (es. testo="rossi 2026/045")."""
    return [Fattura.model_validate(f) for f in reg.trova_fatture(testo, stato)]


@protette.get("/fatture/{id_fattura}", tags=["registro"])
def una_fattura(id_fattura: str) -> Fattura:
    """Una fattura dal suo id (es. F0003)."""
    f = reg.trova_fattura(id_fattura.upper())
    if f is None:
        raise HTTPException(404, f"Fattura {id_fattura} non trovata.")
    return Fattura.model_validate(f)


@protette.get("/scadenze", tags=["registro"])
def scadenze(
    entro_giorni: int = Query(30, ge=0, le=366),
    data_riferimento: Optional[date] = Query(None, description="Di solito oggi; utile per le prove"),
) -> list[Scadenza]:
    """Fatture del registro ancora da pagare che scadono entro N giorni, comprese le già scadute."""
    elenco = reg.in_scadenza(entro_giorni, data_riferimento.isoformat() if data_riferimento else None)
    return [Scadenza(fattura=Fattura.model_validate(f), giorni_alla_scadenza=g, scaduta=g < 0)
            for f, g in sorted(elenco, key=lambda x: x[1])]


@protette.get("/riepilogo", tags=["registro"])
def riepilogo(
    tipo: Literal["mese", "trimestre", "anno"],
    anno: int = Query(..., ge=2000, le=2100),
    numero: Optional[int] = Query(None, ge=1, le=12, description="Mese 1-12 o trimestre 1-4; per l'anno non serve"),
) -> Riepilogo:
    """Totali del periodo (sulla data di emissione, annullate escluse)."""
    if tipo != "anno" and numero is None:
        raise HTTPException(422, f"Per il {tipo} serve anche 'numero'.")
    if tipo == "trimestre" and numero > 4:
        raise HTTPException(422, "Il trimestre va da 1 a 4.")
    numero = None if tipo == "anno" else numero
    return Riepilogo(tipo=tipo, anno=anno, numero=numero, **reg.totali_del_periodo(tipo, anno, numero))


@protette.get("/scadenziario", tags=["scadenziario"])
def scadenziario_da_pagare(
    entro: Optional[date] = Query(None, description="Solo le righe che scadono entro questa data"),
) -> list[RigaScadenziario]:
    """Le righe non saldate dello scadenziario annuale (Excel condiviso), in ordine di scadenza."""
    return [_riga_scadenziario(r) for r in scadenziario.da_pagare(entro.isoformat() if entro else None)]


app.include_router(protette)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
