"""
COLLEGAMENTO A GOOGLE - da lanciare UNA VOLTA SOLA (con Run, non dalla console)
===============================================================================

Cosa succede:
  1. si apre il browser sulla pagina di accesso Google
  2. scegli il tuo account e dai il consenso (vedrai l'avviso "Google non ha verificato questa app":
     è normale, l'app è la tua ed è in modalità test -> Avanzate -> Vai a ... (non sicura) -> Continua)
  3. il programma salva google_token.json: da qui in poi il bot accede a Drive e Gmail da solo
  4. come prova crea la cartella privata su Drive e ti manda un'email di test

Prima serve il file google_credenziali.json nella cartella segreti/ (vedi README).
"""

import os

import google_servizi as g

print("1) Accesso a Google (si apre il browser)...")
g._credenziali()
print("   OK, accesso salvato in google_token.json")

print("2) Cartella privata su Drive...")
id_cartella = g._cartella(g.NOME_CARTELLA_DRIVE)
print(f"   OK, cartella '{g.NOME_CARTELLA_DRIVE}': https://drive.google.com/drive/folders/{id_cartella}")

destinatario = os.getenv("COMMERCIALISTA_EMAIL", "").strip()
if destinatario:
    print(f"3) Email di prova a {destinatario}...")
    g.invia_email(destinatario, "Prova assistente fatture",
                  "Se leggi questa email, l'invio dall'assistente fatture funziona.")
    print("   OK, email inviata: controlla la casella (anche lo spam).")
else:
    print("3) COMMERCIALISTA_EMAIL non impostato nel .env: salto l'email di prova.")

print("\nTutto collegato!")
