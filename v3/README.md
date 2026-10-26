# Assistente fatture v3 — fatture estere, lavoro del mese, MLOps

La v3 porta l'assistente dalla piccola impresa a un **ufficio amministrativo vero**, dove arrivano ogni mese
decine di fatture **estere** (dollari, sterline, corone ceche…), pagate con carte diverse o con bonifico.
Il bot lavora in un **gruppo Telegram**, legge e scrive in **cartelle condivise** e gira in un **container Docker**
su un server, aggiornato solo quando tutti i test passano.

Stesso principio delle versioni precedenti, portato fino in fondo: **l'LLM legge, Python converte e controlla**.
Il modello copia i dati dalla fattura così come sono scritti; date, importi, partite IVA, cambi, scadenze, ratei e
risconti li calcola il codice.

| | v2 | **v3** |
|---|---|---|
| Fatture | italiane, una alla volta | italiane **ed estere**, una alla volta **e a blocchi mensili** |
| Valuta | euro | qualsiasi valuta → **controvalore in euro** (estratto della carta, oppure cambio Banca d'Italia del giorno) |
| Fornitori esteri | — | partita IVA verificata sul **VIES**, anagrafica ricontrollata ogni mese |
| Uscite | registro, riepiloghi | **registrazione contabile**, **scadenziario annuale**, **ratei e risconti** a una data |
| Dove lavora | chat privata | **gruppo Telegram** (risponde solo quando è chiamato) e cartelle condivise |
| Qualità | golden set | **164 test** senza LLM, **MLflow** per scegliere i modelli, **DSPy** per l'interprete delle risposte |
| Rilascio | a mano | **uv** + lock file, **Docker** multi-stadio con i test dentro, **GitHub Actions**, aggiornamento con un comando |

## Cosa fa

| Funzione | Come |
|---|---|
| **Fatture estere** | partita IVA cercata anche nel piè di pagina e normalizzata (prefisso del paese, numeri OSS, `OO99999999999` se manca, mai quella del cliente, mai un IBAN: controllo mod-97); paese dall'indirizzo del fornitore, non da quello della banca; date in ogni lingua (`01/Sep/2026`, `9/1/2026` all'americana riconosciuta dalle altre date del documento) |
| **Controvalore in euro** | prima l'addebito sull'estratto conto della carta (Excel con il cambio, o PDF già in euro), abbinato per importo, nome (anche con alias imparati in chat) e data più vicina; altrimenti il cambio **Banca d'Italia** del giorno della fattura (API pubblica); se non c'è, non lo inventa |
| **Anagrafica fornitori esteri** | verifica **VIES** e registri ufficiali dove esistono; nelle note "nuovo fornitore", "partita IVA / nome / indirizzo cambiati"; controllo automatico ogni mese |
| **Blocco del mese** (`/registra ottobre`) | legge la cartella del mese: scarta copie di cortesia, contabili e doppioni, mette le note di credito in negativo, tiene le pro-forma fuori dalla registrazione; scrive nella stessa cartella la **registrazione contabile** (data = ultimo giorno lavorativo del mese, festivi compresi) e un **riepilogo** di cosa controllare a mano |
| **Scadenziario annuale** | ogni fattura confermata in chat diventa una riga (una per rata); scadenza dalla fattura, oppure dai **termini di pagamento** letti da un Excel dell'amministrazione; rate per fornitore e rate dette a parole ("60% a 7 gg DF e 40% a 30 gg FM"); `/scadenze`, `/saldata` |
| **Ratei e risconti** (`/ratei 31/12/2026`) | a qualsiasi data di chiusura, in proporzione ai giorni del periodo letto nella descrizione; periodi "dal 15 al 15" contati correttamente; Excel con quota, differenza e totali |
| **Controlli** | la partita IVA dell'azienda cliente deve esserci; scadenza prima della data fattura; numero o data illeggibili dal testo → si rilegge la pagina come immagine |

Tutto il resto delle versioni precedenti resta: acquisizione da foto, PDF, vocali e testo, grafo delle bozze
LangGraph con conferma, server MCP in sola lettura, RAG sul contenuto delle fatture.

## MLOps

**Test senza modello.** I 164 test (`tests/`) controllano regole e conversioni senza chiamare l'LLM e senza rete:
girano in pochi secondi, sempre uguali, a ogni modifica. La qualità del modello si misura a parte (golden set).

**Letture salvate.** Del modello si salva solo la risposta grezza, con una chiave che dipende da modello, istruzioni
e schema. Le conversioni Python si rifanno a ogni avvio: correggere una regola e rielaborare un mese intero costa
due minuti e zero chiamate. Se cambiano le istruzioni o lo schema, la chiave cambia e la fattura si rilegge.

**Ambiente riproducibile.** `uv` con `uv.lock`: stesse versioni sul PC, in CI e nel container. Gruppi separati per
gli strumenti che non servono in produzione (`dev`: pytest e MLflow; `dspy`).

**Container.** `Dockerfile` multi-stadio: uno stadio esegue i test, quello di produzione contiene solo codice e
librerie, gira con un utente senza privilegi e non contiene segreti (arrivano dal `.env`, i dati da cartelle
collegate). All'avvio `app/avvio.py` controlla la configurazione e si ferma con un messaggio chiaro se manca qualcosa.

**CI.** `.github/workflows/v3-test.yml`: test e costruzione del container a ogni modifica.
`v3-valutazione.yml`: valutazione con il modello vero, solo a mano (costa qualche centesimo; chiave nei secrets).

**Rilascio sul server.** `server/aggiorna.sh v3.2` scarica quella versione, fa girare i test nel container e riavvia
il bot solo se passano; per tornare indietro si rilancia con la versione precedente. Un caricamento sul repository
non cambia niente sul server finché non lo si decide.

## Esperimenti

**Modello di lettura (MLflow, `app/esperimento.py`).** Stessi golden set per tutti i modelli: 14 fatture italiane
(3 giri) e 7 fatture estere inventate con estratti conto finti (`file_di_prova/estere/`).

| Modello | Italiane | Estere |
|---|---|---|
| gpt-4o-mini | 42/42 | 6/7 |
| **gpt-4.1-mini** (scelto) | **42/42** | **7/7** |

**Interprete delle risposte (DSPy, `app/ottimizza_interprete.py`).** Quando il bot chiede un dato, l'utente risponde
come gli viene ("sì", "il totale è 1.481,35", "sulla fattura non c'è"). Su 48 risposte etichettate
(`valutazione/risposte_utente.json`):

| Variante | Azione corretta |
|---|---|
| A — prompt scritto a mano (gpt-4.1-mini) | 88,9% |
| C — DSPy LabeledFewShot, 16 esempi (gpt-4o-mini) | **98,6%** |
| D — DSPy MIPROv2 | 90,3% |

Gli esempi scelti da DSPy sono esportati in `app/interprete_esempi.json` e usati dal prompt LangChain del bot:
più accurato e con un modello più economico. L'ottimizzatore più sofisticato non è stato il migliore.

**Su un mese vero** (139 fatture, 92 estere, dati non pubblicati): controvalori in euro uguali al centesimo a quelli
calcolati a mano in 31 casi su 31; scadenze uguali in 18 su 19.

## Avvio

```bash
uv sync                                   # dipendenze dal lock file
cp .env.example .env                      # poi compilare i valori (vedi i commenti)
uv run --group dev pytest -q              # test
PYTHONPATH=app uv run python app/avvio.py # bot Telegram
```

Con Docker: `docker compose up -d` (vedi `compose.yaml`). Su un server: `server/INSTALLAZIONE.md`.

Elaborazione di un mese senza Telegram:

```bash
PYTHONPATH=app uv run python app/elabora_mese.py "cartella/10 Ottobre" --amex estratto.xlsx --unicredit estratto.pdf
```

## Configurazione principale (`.env`)

| Variabile | A cosa serve |
|---|---|
| `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN` | segreti: solo nel `.env`, mai nel codice né nell'immagine |
| `TELEGRAM_GRUPPI_AUTORIZZATI` / `TELEGRAM_UTENTI_AUTORIZZATI` | chi può usare il bot (gruppi e/o utenti) |
| `AZIENDA_NOME`, `AZIENDA_PIVA` | l'azienda cliente: non è mai il fornitore, e la sua partita IVA deve essere sulla fattura |
| `CARTELLA_REGISTRAZIONE`, `CARTELLA_SCADENZIARIO` | cartelle condivise del blocco mensile e dello scadenziario |
| `SCADENZIARIO_ANNUALE`, `ARCHIVIA_SU_DRIVE`, `AVVISO_REGIME_IVA` | funzioni da accendere o spegnere |
| `MODELLO_LETTURA_TESTO`, `MODELLO_LETTURA_FOTO`, `MODELLO_INTERPRETE` | modelli scelti con gli esperimenti, non nel codice |

Le regole per fornitore (rate) sono dati, non codice: `dati/regole_scadenze.json`.

## Cartelle

| Cartella | Cosa c'è |
|---|---|
| `app/` | il codice: `elabora_mese.py` (blocco del mese), `estratti_conto.py`, `cambi_bdi.py`, `verifica_piva.py`, `anagrafica_esteri.py`, `termini.py`, `scadenziario.py`, `ratei_risconti.py`, `bot_telegram_v2.py`, … |
| `tests/` | 164 test senza modello e senza rete |
| `file_di_prova/`, `valutazione/` | fatture **inventate**, estratti conto finti, golden set, risultati |
| `server/` | installazione e aggiornamento su un server Linux |

Nessun dato reale nel repository: le fatture e i fornitori degli esempi sono inventati.

## Limiti

- Due addebiti identici lo stesso giorno su carte diverse si distinguono solo se la fattura dice con che carta è stata pagata.
- I ratei a una data sono completi solo quando sono arrivate anche le fatture dei mesi successivi.
- Una cartella condivisa aperta in modifica da una persona mentre il bot ci scrive può creare una copia "in conflitto".
- Per i paesi extra UE senza registro pubblico la partita IVA resta "da verificare a mano".
