# Installazione e aggiornamento su un server

Qualsiasi server Linux con Docker (provato su Ubuntu 26.04, 4 GB di RAM). Il bot è **un solo container**, senza
porte aperte: è lui che va a prendere i messaggi da Telegram (polling), quindi non serve un indirizzo pubblico né un
certificato. Le cartelle condivise con l'amministrazione (ownCloud, Nextcloud o altro servizio WebDAV) si montano
con rclone. Tutto quello che conta sta in pochi posti:

| Dove | Cosa | Backup? |
|---|---|---|
| `/opt/bot-fatture/codice/` | il codice, preso dal repository a una versione precisa | no (è nel repository) |
| `/opt/bot-fatture/.env` | impostazioni e **segreti** (OpenAI, Telegram) | sì, in un posto sicuro |
| `/opt/bot-fatture/dati/` | registro, letture già pagate, anagrafica fornitori esteri, cambi, regole | **sì, ogni giorno** |
| `/mnt/owncloud/` | le cartelle condivise (blocchi mensili e scadenziario) | no (stanno sul servizio di condivisione) |

## 1. Pacchetti (una volta)
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 rclone fuse3 git unattended-upgrades
sudo systemctl enable --now docker
```
Firewall: in entrata solo SSH. In uscita il bot usa solo HTTPS (Telegram, OpenAI, il servizio delle cartelle,
Banca d'Italia, VIES).

## 2. Codice, cartelle e segreti (una volta)
```bash
sudo git config --global credential.helper store      # il token di sola lettura del repository resta sul server
sudo git clone https://INDIRIZZO-DEL-REPOSITORY.git /opt/bot-fatture/codice
sudo mkdir -p /opt/bot-fatture/dati /opt/bot-fatture/segreti /mnt/owncloud /etc/rclone
sudo chown -R 1000:1000 /opt/bot-fatture/dati /opt/bot-fatture/segreti   # 1000 = utente del container
sudo cp /opt/bot-fatture/codice/server/env.esempio /opt/bot-fatture/.env
sudo chmod 600 /opt/bot-fatture/.env      # poi si compilano i valori (vedi i commenti nel file)
```
Per il server conviene un **token di sola lettura** del repository (su GitLab: deploy token, scope `read_repository`).
Dati di partenza, se ci sono: regole di pagamento per fornitore (`regole_scadenze.json`, formato in `app/termini.py`),
alias dei nomi sugli estratti conto, e la cartella `letture/` per non ripagare le letture già fatte.

## 3. Cartelle condivise via WebDAV (una volta)
Serve un **utente dedicato al bot** (non amministratore), con una password per applicazioni, che veda solo le due
cartelle: quella dei blocchi mensili e quella dello scadenziario. La password si scrive al prompt e non resta
nella cronologia della shell:
```bash
read -s -p "Password dell'utente del bot: " P && echo && sudo rclone config create owncloud webdav \
     url=https://INDIRIZZO/remote.php/webdav/ vendor=owncloud user=UTENTE-BOT pass="$P" --obscure \
     --config /etc/rclone/rclone.conf && unset P && sudo chmod 600 /etc/rclone/rclone.conf
echo user_allow_other | sudo tee -a /etc/fuse.conf
sudo cp /opt/bot-fatture/codice/server/rclone-owncloud.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now rclone-owncloud
ls /mnt/owncloud                      # devono comparire le due cartelle
```
Nomi delle cartelle in `compose.yaml` (le collega al container come `/condivise/registrazione` e `/condivise/scadenziario`).

## 4. Avvio
```bash
sudo /opt/bot-fatture/codice/server/aggiorna.sh v3.1      # test nel container, poi avvio
cd /opt/bot-fatture/codice/server && sudo docker compose logs -f     # deve comparire "Bot v2 avviato"
```
Nel gruppo Telegram: si aggiunge il bot, si scrive `/start`, il bot risponde con l'id del gruppo; lo si mette in
`TELEGRAM_GRUPPI_AUTORIZZATI` nel `.env` e si riavvia (`docker compose up -d`).
Da @BotFather: `/setprivacy` → Disable (così nel gruppo il bot riceve anche i file).

## 5. Aggiornamento (a mano, quando c'è una versione nuova)
Un caricamento sul repository **non** cambia niente sul server: si aggiorna solo quando lo si decide, con un comando.
```bash
sudo /opt/bot-fatture/codice/server/aggiorna.sh            # mostra la versione installata e quelle disponibili
sudo /opt/bot-fatture/codice/server/aggiorna.sh v3.2       # scarica v3.2, test nel container, se passano riavvia
```
Se i test falliscono non si installa niente: resta in funzione la versione di prima.

**Tornare indietro:** stesso comando con la versione precedente (`aggiorna.sh v3.1`). I dati non si toccano.

## 6. Backup
Meglio un backup dell'intero server dal pannello del fornitore. In più, per recuperare al volo un singolo file:
```bash
# ogni notte alle 2: copia compressa di dati/ e .env, tenute 30 giorni
0 2 * * * tar czf /backup/bot-fatture-$(date +\%F).tar.gz -C /opt/bot-fatture dati .env && find /backup -name 'bot-fatture-*' -mtime +30 -delete
```

## 7. Controlli
- `docker compose ps` → stato del bot; `docker compose logs --since 1h` → ultimi messaggi.
- Gli errori tecnici (OpenAI che non risponde, scadenziario aperto da qualcuno) arrivano come avviso su Telegram
  a chi è in `AVVISI_TELEGRAM_CHAT_ID`.
- Costi OpenAI: impostare un limite di spesa mensile sull'account.
