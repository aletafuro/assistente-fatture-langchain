"""
AVVIO DEL BOT (anche nel container)
===================================

Prima di caricare tutto, controlla che la configurazione ci sia: se manca qualcosa lo dice in chiaro
e si ferma subito ("fail fast"), invece di cadere più avanti con un errore tecnico.
"""

import os
import sys

OBBLIGATORIE = {
    "OPENAI_API_KEY": "la chiave OpenAI (lettura delle fatture)",
    "TELEGRAM_BOT_TOKEN": "il token del bot Telegram (da BotFather)",
    "TELEGRAM_UTENTI_AUTORIZZATI": "gli id Telegram di chi può usare il bot",
}
CONSIGLIATE = {
    "AZIENDA_NOME": "il nome della propria azienda (il cliente delle fatture)",
    "AZIENDA_PIVA": "la partita IVA della propria azienda",
}


def controlla() -> bool:
    mancanti = [f"  - {nome}: {cosa}" for nome, cosa in OBBLIGATORIE.items() if not os.getenv(nome)]
    for nome, cosa in CONSIGLIATE.items():
        if not os.getenv(nome):
            print(f"Attenzione: manca {nome} ({cosa}). Il bot funziona, ma legge meglio con questa informazione.")
    if mancanti:
        print("Configurazione incompleta, il bot non parte. Mancano:\n" + "\n".join(mancanti) +
              "\nVanno nel file .env (vedi .env.example) o nelle variabili d'ambiente del container.")
        return False
    return True


if __name__ == "__main__":
    if not controlla():
        sys.exit(2)
    import bot_telegram_v2
    bot_telegram_v2.main()
