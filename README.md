# Assistente AI per la gestione delle fatture

Assistente **agentico** su Telegram per le fatture fornitori di una piccola impresa: riceve le fatture come **foto, PDF, messaggi vocali o testo**, ne estrae i dati con l'aiuto dell'utente, le archivia su **Google Drive**, le registra, le controlla e invia i riepiloghi al **commercialista**.

Realizzato con **LangChain** (`create_agent`) e Python.

---

## Cosa fa

| # | Funzione | Come |
|---|---|---|
| 1 | **Acquisizione multicanale** | bot Telegram: testo, foto JPEG/PNG, PDF, vocali/audio (trascritti) |
| 2 | **Estrazione assistita e bozze** | l'LLM estrae fornitore, P.IVA, numero, date, imponibile, IVA, totale in una **bozza persistente**; se manca un dato lo chiede; l'utente modifica, conferma o annulla |
| 3 | **Archiviazione e registrazione** | originale in una cartella **privata** di Google Drive (una sottocartella per anno); dati nel registro JSON |
| 4 | **Controlli contabili** | importi in **centesimi interi**, coerenza imponibile + IVA = totale, **duplicati**, P.IVA di 11 cifre, **IVA non ordinaria** segnalata (inversione contabile, aliquote ridotte, esenzioni) |
| 5 | **Ciclo di vita** | da pagare / pagata; **annullamento logico** (esce dai totali, resta nello storico con il motivo) |
| 6 | **Riepiloghi** | mensili, trimestrali, annuali, su richiesta in chat |
| 7 | **Invio al commercialista** | file **XLSX** generato dal registro + email Gmail con allegato e **link privati** agli originali (condivisi in sola lettura solo con il commercialista); conferma obbligatoria prima dell'invio |
| 8 | **Robustezza e avvisi** | errori gestiti senza crash; **avvisi configurabili** nel `.env` (canali, destinatari, soglie); controllo giornaliero delle scadenze |

### Esempi di conversazione
- *(invio di una foto)* → l'assistente mostra i dati letti, segnala che manca la scadenza e propone *emissione + 30 giorni* → "sì va bene" → "salvala" → registrata e archiviata su Drive.
- "Ho pagato la fattura di Beta Logistica il 20 settembre" → cerca la fattura e la segna pagata.
- "Quanto ho speso nel terzo trimestre?" · "Quali fatture scadono nei prossimi 15 giorni?"
- "Mandami il file Excel di settembre" → il file arriva in chat.
- "Invia al commercialista il riepilogo del terzo trimestre" → riassunto + richiesta di conferma → email.
- Comandi: `/start` (benvenuto + bozze in sospeso), `/stato` (configurazione avvisi), `/controllo` (controllo scadenze immediato).

---

## Architettura

```
                 ┌──────────────────────── bot_telegram.py ────────────────────────┐
 Telegram  ───>  │ handler: testo | foto | documento | vocale (→ trascrizione.py)  │
                 │ utenti autorizzati · file in dati/ricevuti · JobQueue scadenze  │
                 └──────────────────────────────┬──────────────────────────────────┘
                                                │ messaggio + id chat
                 ┌──────────────── agente_fatture.py (create_agent) ───────────────┐
                 │ gpt-4.1-mini · system prompt con le regole · memoria per chat   │
                 │ middleware: un tool alla volta, data di oggi sempre aggiornata  │
                 └──────────────────────────────┬──────────────────────────────────┘
                                                │ sceglie i tool (strumenti_fatture.py, 15 tool)
      ┌───────────────────┬─────────────────────┼─────────────────────┬──────────────────────┐
 estrazione.py      bozze_fatture.py     registro_fatture.py     archivio.py          commercialista.py
 PDF · foto ·       bozze persistenti,   registro JSON: paga,    originali su         XLSX + email con
 testo → dati       mancanti, avvisi,    annulla, riepiloghi,    Google Drive         link privati
 (LLM legge)        proposta scadenza    scadenze, duplicati          └── google_servizi.py (OAuth, Drive, Gmail)
                                                                  avvisi.py: log, soglie, avvisi tecnici e contabili
```

**Principio guida: l'LLM legge, Python converte e conta.** L'LLM copia importi e date come sono scritti; Python li converte in centesimi interi e in date `AAAA-MM-GG`, e fa **tutti** i controlli e i totali. L'LLM non fa mai calcoli.

| Cartella / file | Contenuto |
|---|---|
| `codice/` | tutto il codice (vedi tabella moduli sotto) |
| `file_di_prova/` | le fatture usate per le prove: 9 PDF, 3 foto, 1 vocale, 1 testo |
| `valutazione/` | `golden_set.json` (dati attesi), `VALUTAZIONE.md` e `risultati_valutazione.json` |
| `esempio/registro_esempio.json` | registro di esempio popolato dall'uso reale del bot |
| `RELAZIONE.md` | relazione tecnica |
| `.env.example` | variabili di configurazione da compilare |
| `dati/`, `log/`, `segreti/`, `.env` | creati in esecuzione, **esclusi dal repository** |

| Modulo | Ruolo |
|---|---|
| `bot_telegram.py` | punto di ingresso: il bot |
| `agente_fatture.py` | l'agente LangChain e le sue regole |
| `strumenti_fatture.py` | i 15 tool (`@tool`) a disposizione dell'agente |
| `estrazione.py` | estrazione dati da PDF, foto e testo (output strutturato Pydantic) |
| `trascrizione.py` | trascrizione dei vocali |
| `fatture_comuni.py` | schema `DatiFattura`, conversioni importi/date, confronti |
| `bozze_fatture.py` | bozze persistenti e relativi controlli |
| `registro_fatture.py` | registro, duplicati, pagamenti, annullamento logico, riepiloghi, scadenze |
| `archivio.py` | archiviazione degli originali su Drive (con riprova) |
| `google_servizi.py` | accesso OAuth, Drive, Gmail |
| `commercialista.py` | file Excel e invio email |
| `avvisi.py` | log e avvisi configurabili |
| `config.py` | percorsi e caricamento del `.env` |
| `collega_google.py` | collegamento a Google (da eseguire una volta) |
| `valuta_golden_set.py` | valutazione dell'estrazione |

---

## Requisiti
- Python **3.12 o superiore** (sviluppato con 3.13)
- Una chiave **OpenAI API**
- Un account **Telegram**
- Un account **Google** (Gmail) per Drive e l'invio email

## Installazione

```bash
git clone <url-del-repository>
cd assistente-fatture
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # su Windows: copy .env.example .env
```

Poi compila il file `.env` seguendo i passi qui sotto.

## Configurazione delle integrazioni

### 1. OpenAI
Inserisci la chiave in `OPENAI_API_KEY` (oppure impostala come variabile d'ambiente del sistema).

### 2. Bot Telegram
1. Su Telegram apri **@BotFather** (spunta blu) → `/newbot` → scegli nome e username (deve finire in `bot`).
2. Copia il **token** in `TELEGRAM_BOT_TOKEN`.
3. Avvia il bot (vedi *Esecuzione*) e scrivigli `/start`: risponderà "non autorizzato" indicando il tuo **id**.
4. Inserisci l'id in `TELEGRAM_UTENTI_AUTORIZZATI` (e in `AVVISI_TELEGRAM_CHAT_ID` per ricevere gli avvisi) e riavvia.

Il bot risponde **solo** agli utenti autorizzati: le fatture sono dati aziendali.

### 3. Google Drive e Gmail (un solo collegamento OAuth)
Su [console.cloud.google.com](https://console.cloud.google.com):
1. **Nuovo progetto** (es. `assistente-fatture`) e selezionalo.
2. Abilita **Google Drive API** e **Gmail API**.
3. **Google Auth Platform** (schermata di consenso OAuth) → *Inizia*: nome app, email di assistenza, pubblico **Esterno**.
4. **Pubblico → Utenti di test** → aggiungi il tuo indirizzo Gmail.
5. **Client → Crea client → App desktop** → *Scarica JSON*.
6. Rinomina il file in `google_credenziali.json` e mettilo nella cartella **`segreti/`** del progetto.
7. Compila `COMMERCIALISTA_EMAIL` (e, se vuoi, `DRIVE_NOME_CARTELLA`) nel `.env`.
8. Esegui **una volta**:
   ```bash
   python codice/collega_google.py
   ```
   Si apre il browser: accedi, e all'avviso *"Google non ha verificato questa app"* scegli *Avanzate → Vai a …* (è la tua app, in modalità test), concedi i permessi. Lo script crea `segreti/google_token.json`, la cartella privata su Drive e invia un'email di prova.

Permessi richiesti, i **minimi**: `drive.file` (solo i file creati dall'app, non il resto del Drive) e `gmail.send` (solo invio, non lettura). Non serve alcuna "password per le app".

### 4. Avvisi
Tutto nel `.env` (vedi i commenti in `.env.example`): canali (`telegram`, `email`), destinatari, soglia importo, ora e anticipo del controllo scadenze, soglia e pausa degli avvisi tecnici.

## Esecuzione

```bash
python codice/bot_telegram.py
```

All'avvio compare `Controllo scadenze programmato ogni giorno alle 09:00` e `Bot avviato`. Il bot resta attivo finché non lo fermi (Ctrl+C). I dati vengono salvati in `dati/`, il log in `log/errori.log`.

### Valutazione dell'estrazione

```bash
python codice/valuta_golden_set.py 3
```

Riesegue l'estrazione sulle 14 fatture del golden set (9 PDF, 3 foto, 1 vocale, 1 testo) per 3 giri e scrive `valutazione/VALUTAZIONE.md`. Ultimo risultato: **42 estrazioni corrette su 42** (dettagli nel file; i limiti osservati durante lo sviluppo sono nella relazione).

---

## Sicurezza e privacy
- Nessun segreto nel codice o nel repository: token, chiavi e credenziali stanno in `.env` e `segreti/`, esclusi da `.gitignore`.
- Bot limitato agli utenti autorizzati.
- File su Drive **privati**; al commercialista vengono condivisi in sola lettura solo quelli inviati.
- Permessi Google minimi (`drive.file`, `gmail.send`).
- Azioni irreversibili (registrazione, invio email, annullamento) solo dopo conferma esplicita dell'utente.

## Limiti noti
Descritti in dettaglio nella `RELAZIONE.md`: la trascrizione dei vocali può sbagliare cifre (intercettato dal controllo sulla P.IVA e dalla verifica dell'utente), le foto inviate come "foto" vengono compresse da Telegram (meglio come file), la memoria della conversazione si azzera al riavvio (le bozze invece restano), l'app Google è in modalità test.
