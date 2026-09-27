"""
SERVER MCP DEL REGISTRO FATTURE (v2) - SOLA LETTURA
===================================================

Espone il registro con il Model Context Protocol: lo usa l'agente della v2, ma lo può usare
qualunque client MCP (Claude Desktop, Claude Code, Cursor...) senza riscrivere i tool.

Scelta di sicurezza: SOLO LETTURA. Cercare, riassumere, scadenze, fornitori.
Pagare, annullare e registrare restano fuori: un server MCP può finire collegato a client che
non controlliamo, e la protezione vera è non esporre l'azione (non affidarsi al prompt).

Avvio: lo avvia il client in modalità stdio (non va lanciato a mano). Niente print():
lo standard output è il canale del protocollo.
"""

from typing import Literal, Optional

import percorsi_v2  # noqa: F401

import registro_fatture as reg
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("RegistroFatture")


@mcp.tool()
def cerca_fatture(testo: str = "", stato: Literal["tutte", "da_pagare", "pagata", "annullata"] = "tutte") -> str:
    """Cerca fatture fornitori nel registro per nome del fornitore o numero, filtrando per stato.
    Serve anche a trovare l'id di una fattura (es. F0003)."""
    return reg.cerca_fatture(testo, stato)


@mcp.tool()
def riepilogo(tipo: Literal["mese", "trimestre", "anno"], anno: int, numero: Optional[int] = None) -> str:
    """Riepilogo delle fatture attive di un periodo: numero, imponibile, IVA, totale, da pagare,
    totale per fornitore, IVA da verificare. numero = mese (1-12) o trimestre (1-4); non serve per l'anno."""
    return reg.riepilogo(tipo, anno, numero)


@mcp.tool()
def fatture_in_scadenza(entro_giorni: int = 30) -> str:
    """Fatture ancora da pagare che scadono entro N giorni da oggi, comprese quelle già scadute."""
    return reg.fatture_in_scadenza(entro_giorni)


@mcp.tool()
def fornitore_piu_costoso(anno: int) -> str:
    """Il fornitore con il totale fatturato più alto nell'anno indicato, escluse le fatture annullate."""
    totali = {}
    for f in reg.fatture_del_periodo("anno", anno):
        totali[f["fornitore"]] = totali.get(f["fornitore"], 0) + (f["totale_cent"] or 0)
    if not totali:
        return f"Nessuna fattura attiva nel {anno}."
    nome, tot = max(totali.items(), key=lambda x: x[1])
    return f"Nel {anno} il fornitore più costoso è {nome}: {reg.centesimi_in_euro(tot)}."


@mcp.resource("fatture://fornitori")
def elenco_fornitori() -> str:
    """Elenco dei fornitori con numero di fatture attive e totale fatturato."""
    totali = {}
    for f in reg.carica_registro():
        if not f["annullata"]:
            n, s = totali.get(f["fornitore"], (0, 0))
            totali[f["fornitore"]] = (n + 1, s + (f["totale_cent"] or 0))
    return "\n".join(f"{nome}: {n} fatture, {reg.centesimi_in_euro(s)}"
                     for nome, (n, s) in sorted(totali.items(), key=lambda x: -x[1][1]))


if __name__ == "__main__":
    mcp.run(transport="stdio")
