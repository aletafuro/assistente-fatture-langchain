"""
ARCHIVIAZIONE DEGLI ORIGINALI SU GOOGLE DRIVE
=============================================

Quando una bozza viene confermata, la fattura entra nel registro E il suo originale
(PDF, foto, vocale, o il testo scritto in chat salvato come .txt) va su Drive.

Nome del file su Drive, sempre uguale e ordinabile:
     AAAA-MM-GG_Fornitore_Numero.estensione     es. 2026-06-10_Alfa_Forniture_SRL_2026-037.pdf
dentro la cartella privata "Fatture - Assistente AI" / anno.

ROBUSTEZZA: se Drive non risponde, la fattura resta comunque REGISTRATA (non si perde niente)
e viene segnata "archiviazione: in_attesa". Con riprova_archiviazioni() si ricaricano dopo.
"""

import re
from pathlib import Path

import registro_fatture as reg
from google_servizi import ErroreGoogle, carica_su_drive


def _nome_su_drive(f: dict, estensione: str) -> str:
    def pulito(testo):
        return re.sub(r"[^A-Za-z0-9]+", "_", testo or "").strip("_")
    return f"{f['data_emissione']}_{pulito(f['fornitore'])}_{pulito(f['numero'])}{estensione}"


def archivia_fattura(id_fattura: str) -> str:
    f = reg.trova_fattura(id_fattura)
    if f is None:
        return f"Nessuna fattura con id {id_fattura}."
    if f.get("drive_link"):
        return f"{f['id']} è già archiviata su Drive: {f['drive_link']}"
    originale = f.get("percorso_originale")
    if not originale:
        reg.aggiorna_campi(id_fattura, {"archiviazione": "nessun_originale"})
        return f"{f['id']}: nessun file originale da archiviare."
    try:
        caricato = carica_su_drive(Path(originale), _nome_su_drive(f, Path(originale).suffix),
                                   anno=f["data_emissione"][:4])
    except ErroreGoogle as errore:
        reg.aggiorna_campi(id_fattura, {"archiviazione": "in_attesa", "errore_archiviazione": str(errore)})
        return (f"ATTENZIONE: {f['id']} è registrata, ma l'originale NON è stato archiviato su Drive: {errore} "
                "Riproverò più tardi (tool riprova_archiviazione).")
    reg.aggiorna_campi(id_fattura, {"archiviazione": "fatto", "drive_id": caricato["id"],
                                    "drive_link": caricato["link"], "errore_archiviazione": None})
    return f"Originale archiviato su Google Drive: {caricato['link']}"


def riprova_archiviazioni() -> str:
    in_attesa = [f["id"] for f in reg.carica_registro() if f.get("archiviazione") == "in_attesa"]
    if not in_attesa:
        return "Nessuna fattura in attesa di archiviazione."
    return "\n".join(archivia_fattura(i) for i in in_attesa)
