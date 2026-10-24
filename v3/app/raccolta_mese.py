"""
RACCOLTA DEL MESE: le fatture e gli estratti conto mandati in chat, poi elaborati insieme
=======================================================================================

   /mese      -> si apre una raccolta (una cartella per chat, in dati/raccolte/)
   file       -> PDF, foto, Excel o uno ZIP con la cartella del mese: finiscono nella raccolta
   elabora    -> gli estratti conto si riconoscono da soli (Amex = Excel con "Foreign Spend Amount",
                 UniCredit = PDF "estratto conto carta di credito"), il resto sono fatture;
                 si esegue elabora_mese e il bot rimanda in chat i file prodotti
   annulla    -> la raccolta si chiude senza elaborare

La logica sta qui, separata dalla chat: si prova con i test senza Telegram.
"""

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

RACCOLTE = config.DATI / "raccolte"
APERTE = config.DATI / "raccolte_aperte.json"
ESTENSIONI = {".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".zip"}


def _aperte() -> dict:
    return json.loads(APERTE.read_text(encoding="utf-8")) if APERTE.exists() else {}


def _salva(aperte: dict) -> None:
    APERTE.write_text(json.dumps(aperte, indent=1), encoding="utf-8")


def aperta(chat_id) -> Optional[Path]:
    percorso = _aperte().get(str(chat_id))
    return Path(percorso) if percorso else None


def apri(chat_id) -> Path:
    """Nuova raccolta (o quella già aperta: si continua ad aggiungere)."""
    esistente = aperta(chat_id)
    if esistente:
        return esistente
    cartella = RACCOLTE / str(chat_id) / datetime.now().strftime("%Y%m%d_%H%M%S")
    cartella.mkdir(parents=True, exist_ok=True)
    aperte = _aperte()
    aperte[str(chat_id)] = str(cartella)
    _salva(aperte)
    return cartella


def chiudi(chat_id) -> None:
    aperte = _aperte()
    aperte.pop(str(chat_id), None)
    _salva(aperte)


def _estrai_zip(zip_path: Path, destinazione: Path) -> int:
    """Solo i file utili, senza seguire percorsi strani dentro lo ZIP (es. '../../file')."""
    estratti = 0
    with zipfile.ZipFile(zip_path) as archivio:
        for voce in archivio.infolist():
            nome = Path(voce.filename).name
            if voce.is_dir() or not nome or nome.startswith((".", "__MACOSX")) or "__MACOSX" in voce.filename:
                continue
            if Path(nome).suffix.lower() not in ESTENSIONI - {".zip"}:
                continue
            sottocartella = Path(voce.filename).parent.name or ""
            obiettivo = destinazione / (f"{sottocartella} - {nome}" if sottocartella else nome)
            with archivio.open(voce) as sorgente, open(obiettivo, "wb") as uscita:
                shutil.copyfileobj(sorgente, uscita)
            estratti += 1
    zip_path.unlink()
    return estratti


def aggiungi(chat_id, file_ricevuto: Path, nome_originale: str) -> str:
    """Sposta un file ricevuto nella raccolta. Restituisce il messaggio per l'utente."""
    cartella = aperta(chat_id)
    estensione = Path(nome_originale).suffix.lower()
    if estensione not in ESTENSIONI:
        return f"'{nome_originale}' non è un formato che uso per il mese (PDF, foto, Excel o ZIP): l'ho ignorato."
    obiettivo = cartella / Path(nome_originale).name
    shutil.move(str(file_ricevuto), obiettivo)
    if estensione == ".zip":
        n = _estrai_zip(obiettivo, cartella)
        return f"Dallo ZIP ho preso {n} file. {stato(chat_id)}"
    return stato(chat_id)


def riconosci_estratto(percorso: Path) -> Optional[str]:
    """'amex', 'unicredit' oppure None (= una fattura). Si guarda il CONTENUTO, non solo il nome del file."""
    estensione = percorso.suffix.lower()
    if estensione == ".xlsx":
        try:
            from openpyxl import load_workbook
            foglio = load_workbook(percorso, read_only=True).worksheets[0]
            for i, riga in enumerate(foglio.iter_rows(values_only=True)):
                testo = " ".join(str(c) for c in riga if c)
                if "Foreign Spend Amount" in testo or "Dettagli completi" in testo:
                    return "amex"
                if i > 40:
                    break
        except Exception:
            return None
        return "excel"                      # un Excel che non è l'Amex: non è una fattura
    if estensione == ".pdf":
        try:
            from fatture_comuni import leggi_pdf
            testo = leggi_pdf(percorso)[:3000].upper()
        except Exception:
            return None
        if "ESTRATTO CONTO" in testo and "CARTA DI CREDITO" in testo:
            return "unicredit"
    return None


def stato(chat_id) -> str:
    cartella = aperta(chat_id)
    file = [p for p in cartella.iterdir() if p.is_file()]
    estratti = [p for p in file if riconosci_estratto(p) in ("amex", "unicredit")]
    fatture = [p for p in file if p.suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png"} and p not in estratti]
    return (f"Nella raccolta: {len(fatture)} fatture e {len(estratti)} estratti conto"
            + (f" ({', '.join(riconosci_estratto(p).upper() for p in estratti)})" if estratti else "")
            + ". Quando hai finito scrivi \"elabora\" (oppure \"annulla\").")


def elabora(chat_id, mese: Optional[str] = None) -> tuple:
    """Esegue l'elaborazione del mese sulla raccolta. Restituisce (messaggio, file da mandare in chat)."""
    import elabora_mese
    cartella = aperta(chat_id)
    amex = next((p for p in cartella.iterdir() if riconosci_estratto(p) == "amex"), None)
    unicredit = next((p for p in cartella.iterdir() if riconosci_estratto(p) == "unicredit"), None)
    risultato = elabora_mese.elabora(cartella, amex, unicredit)
    mese = mese or _mese_prevalente(risultato["fatture"])
    uscita = cartella / "risultati"
    creati = elabora_mese.scrivi_file(risultato, uscita, mese, amex)
    estere = sum(f["estera"] for f in risultato["fatture"])
    senza_euro = sum(1 for f in risultato["fatture"] if f["estera"] and f["importo_eur"] is None)
    messaggio = (f"Elaborato il mese {mese}: {len(risultato['fatture'])} fatture ({estere} estere), "
                 f"{len(risultato['saltati'])} file saltati.\n"
                 f"Estratti conto usati: {'Amex' if amex else '-'}, {'UniCredit' if unicredit else '-'}.\n"
                 + (f"ATTENZIONE: {senza_euro} fatture estere senza controvalore in euro, vedi il riepilogo.\n"
                    if senza_euro else "")
                 + "Ti mando i file: registrazione contabile (solo estere), scadenziario, "
                 + ("estratto Amex con i controvalori, " if amex else "") + "riepilogo da controllare.")
    chiudi(chat_id)
    return messaggio, creati


def _mese_prevalente(fatture: list) -> str:
    """Il mese con più fatture (es. '09-2026'), per dare il nome ai file."""
    conteggio = {}
    for f in fatture:
        if f.get("data_emissione"):
            chiave = f"{f['data_emissione'][5:7]}-{f['data_emissione'][:4]}"
            conteggio[chiave] = conteggio.get(chiave, 0) + 1
    return max(conteggio, key=conteggio.get) if conteggio else datetime.now().strftime("%m-%Y")
