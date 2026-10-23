"""
GOOGLE DRIVE E GMAIL - archiviazione degli originali e invio email
===================================================================

Funzioni coperte qui:
   3. Archiviazione degli originali in una cartella PRIVATA di Google Drive
   7. Invio via email al commercialista, con file allegato e LINK PRIVATI ai documenti

COME FUNZIONA L'ACCESSO A GOOGLE (OAuth):
   Il programma non conosce la tua password Google. La prima volta si apre il browser,
   tu accedi a Google e dai il permesso ("consenso") al programma. Google restituisce un
   "gettone" (token) che salviamo in google_token.json: le volte dopo il browser non serve più.

   Permessi chiesti (scope) - i MINIMI necessari:
     drive.file  -> il programma vede e gestisce SOLO i file che ha creato lui, non tutto il tuo Drive
     gmail.send  -> il programma può SOLO inviare email, non leggerle

"LINK PRIVATI": i file su Drive restano privati (visibili solo a te). Per il commercialista
li condividiamo in sola lettura con il SUO indirizzo: il link funziona solo per lui,
non per chiunque lo riceva.

File necessari, nella cartella segreti/ (NON vanno nel repository):
   google_credenziali.json  -> scaricato dalla Google Cloud Console (una volta sola)
   google_token.json        -> creato da solo al primo accesso (collega_google.py)
"""

import base64
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import avvisi
import config

CREDENZIALI = config.GOOGLE_CREDENZIALI
TOKEN = config.GOOGLE_TOKEN
PERMESSI = ["https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/gmail.send"]

NOME_CARTELLA_DRIVE = os.getenv("DRIVE_NOME_CARTELLA", "Fatture - Assistente AI")


class ErroreGoogle(Exception):
    """Errore 'gentile': il messaggio si può mostrare così com'è all'utente."""


# ---------------------------------------------------------------------------
# ACCESSO
# ---------------------------------------------------------------------------

def _credenziali() -> Credentials:
    cred = None
    if TOKEN.exists():
        cred = Credentials.from_authorized_user_file(str(TOKEN), PERMESSI)
    if cred and cred.valid:
        return cred
    if cred and cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())          # rinnova il gettone scaduto, senza browser
        except Exception:
            cred = None
    if not cred or not cred.valid:
        if not CREDENZIALI.exists():
            raise ErroreGoogle("Manca il file google_credenziali.json: Google Drive e Gmail non sono configurati.")
        flusso = InstalledAppFlow.from_client_secrets_file(str(CREDENZIALI), PERMESSI)
        cred = flusso.run_local_server(port=0)   # apre il browser per il consenso
    TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return cred


def _drive():
    return build("drive", "v3", credentials=_credenziali(), cache_discovery=False)


def _gmail():
    return build("gmail", "v1", credentials=_credenziali(), cache_discovery=False)


# ---------------------------------------------------------------------------
# DRIVE: cartelle e caricamento
# ---------------------------------------------------------------------------

def _cartella(nome: str, dentro: Optional[str] = None) -> str:
    """Restituisce l'id di una cartella Drive, creandola se non esiste ancora."""
    drive = _drive()
    query = f"name = '{nome}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if dentro:
        query += f" and '{dentro}' in parents"
    trovate = drive.files().list(q=query, fields="files(id)", spaces="drive").execute().get("files", [])
    if trovate:
        return trovate[0]["id"]
    dati = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    if dentro:
        dati["parents"] = [dentro]
    return drive.files().create(body=dati, fields="id").execute()["id"]


def carica_su_drive(percorso: Path, nome_su_drive: str, anno: Optional[str] = None) -> dict:
    """
    Carica un file nella cartella privata (con una sottocartella per anno).
    Restituisce {'id': ..., 'link': ...}. Il link si apre solo con il tuo account Google.
    """
    percorso = Path(percorso)
    if not percorso.exists():
        raise ErroreGoogle(f"Il file originale {percorso.name} non esiste più sul computer.")
    try:
        cartella = _cartella(NOME_CARTELLA_DRIVE)
        if anno:
            cartella = _cartella(anno, dentro=cartella)
        media = MediaFileUpload(str(percorso), resumable=False)
        creato = _drive().files().create(
            body={"name": nome_su_drive, "parents": [cartella]},
            media_body=media, fields="id, webViewLink").execute()
    except ErroreGoogle:
        raise
    except Exception as errore:
        avvisi.errore_tecnico("Google Drive", errore)
        raise ErroreGoogle(f"Google Drive non è raggiungibile ({type(errore).__name__}).")
    return {"id": creato["id"], "link": creato["webViewLink"]}


def condividi_in_lettura(id_file: str, email: str) -> None:
    """Dà accesso in SOLA LETTURA a un indirizzo preciso. Il file resta privato per tutti gli altri."""
    _drive().permissions().create(
        fileId=id_file, body={"type": "user", "role": "reader", "emailAddress": email},
        sendNotificationEmail=False).execute()


# ---------------------------------------------------------------------------
# GMAIL: invio con allegato
# ---------------------------------------------------------------------------

def invia_email(destinatario: str, oggetto: str, testo: str, allegato: Optional[Path] = None,
                segnala_errori: bool = True) -> None:
    """segnala_errori=False quando l'email È un avviso: se fallisce, non mandiamo un avviso sull'avviso."""
    messaggio = EmailMessage()
    messaggio["To"] = destinatario
    messaggio["Subject"] = oggetto
    messaggio.set_content(testo)
    if allegato:
        allegato = Path(allegato)
        messaggio.add_attachment(
            allegato.read_bytes(), maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=allegato.name)
    grezzo = base64.urlsafe_b64encode(messaggio.as_bytes()).decode()
    try:
        _gmail().users().messages().send(userId="me", body={"raw": grezzo}).execute()
    except Exception as errore:
        if segnala_errori:
            avvisi.errore_tecnico("Gmail", errore)
        raise ErroreGoogle(f"Gmail non è raggiungibile, email non inviata ({type(errore).__name__}).")
