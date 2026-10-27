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
| Per altri programmi | server MCP (per agenti AI) | anche **API REST FastAPI** in sola lettura, con chiave e documentazione OpenAPI |
| Qualità | golden set | **182 test** senza LLM, **MLflow** per scegliere i modelli, **DSPy** per l'interprete delle risposte, **RAGAS** per il RAG, tracce **Langfuse** |
| RAG | indice in memoria | in memoria **o su Postgres + pgvector**, confrontati con lo stesso golden set |
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

## API REST (FastAPI)

Il bot è fatto per le persone; l'API (`app/api_fatture.py`) è fatta per gli altri programmi: un gestionale, un foglio
di calcolo, una dashboard, uno script che ogni mattina scarica le scadenze. Risponde in JSON con campi fissi,
descritti da modelli Pydantic, e pubblica da sola la documentazione OpenAPI su `/docs`, dove le chiamate si provano
dal browser.

| Chiamata | Cosa restituisce |
|---|---|
| `GET /fatture?testo=&stato=` | ricerca nel registro, la stessa della chat |
| `GET /fatture/{id}` | una fattura (404 se non c'è) |
| `GET /scadenze?entro_giorni=30` | fatture da pagare entro N giorni, le già scadute per prime |
| `GET /riepilogo?tipo=mese&anno=2026&numero=9` | totali del periodo, per fornitore, IVA da verificare |
| `GET /scadenziario?entro=2026-11-30` | righe non saldate dello scadenziario annuale (Excel) |
| `GET /salute` | controllo che il servizio sia acceso (senza chiave, senza dati) |

Scelte:
- **Sola lettura**, come il server MCP: registrare, pagare e annullare restano in chat, dove una persona conferma.
- **Chiave** nell'header `X-API-Key` (`API_CHIAVE` nel `.env`, confronto in tempo costante); senza chiave l'API è spenta.
- **Importi in centesimi interi** come nel registro; i percorsi dei file sul server non escono mai.
- **Stessa logica della chat**: ricerca, scadenze e totali vengono dalle stesse funzioni di `registro_fatture.py`.
- Nel `compose.yaml` è un secondo servizio con la stessa immagine, dati montati in sola lettura e porta aperta solo
  su `127.0.0.1`; per esporla fuori serve un proxy HTTPS davanti.

```bash
API_CHIAVE=una-chiave uv run uvicorn api_fatture:app --app-dir app --port 8000
curl -H "X-API-Key: una-chiave" "http://127.0.0.1:8000/scadenze?entro_giorni=15"
```

## MLOps

**Test senza modello.** I 182 test (`tests/`) controllano regole e conversioni senza chiamare l'LLM e senza rete:
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

**Valutazione del RAG (RAGAS, `app/valuta_rag.py`).** Il RAG risponde a domande sul contenuto delle fatture
("chi ci ha venduto il toner?"). Golden set: 16 domande sulle fatture inventate di prova, con la risposta giusta e
le fatture dove si trova; due domande non hanno risposta nelle fatture ("abbiamo comprato sedie da ufficio?"), e il
RAG deve dirlo. Due livelli di misura:

- **ricerca**, in Python, gratis e ripetibile: la fattura giusta è tra le prime 4 (hit, recall) e in che posizione (MRR);
- **risposta**, con **RAGAS** (un LLM fa da giudice): `faithfulness` (ogni affermazione è scritta nelle fatture trovate,
  cioè niente invenzioni), `context_recall`, `context_precision`, `factual_correctness`, `answer_relevancy`.

| Indice | hit@4 | recall@4 | MRR | faithfulness | context recall | context precision | factual correctness | answer relevancy |
|---|---|---|---|---|---|---|---|---|
| in memoria | 1,00 | 1,00 | 0,92 | 0,95 | 1,00 | 0,87 | 0,61 | 0,78 |
| **pgvector** | 1,00 | 1,00 | 0,92 | 0,99 | 1,00 | 0,87 | 0,57 | 0,77 |

Cosa dicono i numeri:
- **pgvector non cambia la qualità**: stesse fatture, nello stesso ordine, in 16 domande su 16. Cambia dove vive
  l'indice: resta salvato, all'avvio si calcolano gli embedding solo delle fatture nuove, regge migliaia di documenti.
- Le differenze di RAGAS tra le due righe (0,95 / 0,99) sono **rumore del giudice**: la ricerca è identica e 12 risposte
  su 16 sono uguali parola per parola. Prima di dire che una modifica migliora qualcosa, la differenza deve superare
  questo rumore.
- `factual_correctness` è bassa perché le risposte giuste del golden set hanno più dettagli (quantità, importi) di
  quelle del bot: misura la completezza più della correttezza. `answer_relevancy` dà 0 alla risposta onesta "la
  fattura non dice cosa è stato comprato": la metrica penalizza le risposte del tipo "non lo so". Per questo i
  risultati domanda per domanda sono in `valutazione/VALUTAZIONE_RAG_memoria.md` e `VALUTAZIONE_RAG_pgvector.md`.
- La prima prova su pgvector aveva **hit 0,80**: la valutazione ha trovato un difetto vero. In `langchain-postgres`
  l'id di un documento vale per tutta la tabella, non per la collezione: la "F0001" di un'altra collezione sovrascriveva
  quella della valutazione. Ora l'id è `collezione/F0001`, con un test che lo controlla.

**Osservabilità (Langfuse, `app/osservabilita.py`).** Con le chiavi nel `.env`, ogni chiamata dell'agente, del router
e del grafo delle bozze diventa una traccia su Langfuse (domanda, risposta, tool usati, tempi, token), raggruppata per
chat; la valutazione del RAG manda una traccia per domanda con i punteggi RAGAS accanto. Senza chiavi è spenta.

**Su un mese vero** (139 fatture, 92 estere, dati non pubblicati): controvalori in euro uguali al centesimo a quelli
calcolati a mano in 31 casi su 31; scadenze uguali in 18 su 19.

## Avvio

```bash
uv sync                                   # dipendenze dal lock file
cp .env.example .env                      # poi compilare i valori (vedi i commenti)
uv run --group dev pytest -q              # test
uv run --group dev --group valutazione python app/valuta_rag.py   # RAG con RAGAS (qualche centesimo)
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
| `RAG_INDICE`, `PGVECTOR_PASSWORD` | indice del RAG: `memoria` (predefinito) o `pgvector` (`docker compose --profile pgvector up -d`) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | tracce delle chiamate all'LLM su Langfuse (facoltative) |
| `API_CHIAVE` | chiave dell'API REST (vuota = API spenta) |

Le regole per fornitore (rate) sono dati, non codice: `dati/regole_scadenze.json`.

## Cartelle

| Cartella | Cosa c'è |
|---|---|
| `app/` | il codice: `elabora_mese.py` (blocco del mese), `estratti_conto.py`, `cambi_bdi.py`, `verifica_piva.py`, `anagrafica_esteri.py`, `termini.py`, `scadenziario.py`, `ratei_risconti.py`, `bot_telegram_v2.py`, … |
| `tests/` | 182 test senza modello e senza rete (quello su pgvector usa un Postgres vero, con embedding finti) |
| `file_di_prova/`, `valutazione/` | fatture **inventate**, estratti conto finti, golden set, risultati |
| `server/` | installazione e aggiornamento su un server Linux |

Nessun dato reale nel repository: le fatture e i fornitori degli esempi sono inventati.

## Limiti

- Due addebiti identici lo stesso giorno su carte diverse si distinguono solo se la fattura dice con che carta è stata pagata.
- I ratei a una data sono completi solo quando sono arrivate anche le fatture dei mesi successivi.
- Una cartella condivisa aperta in modifica da una persona mentre il bot ci scrive può creare una copia "in conflitto".
- Per i paesi extra UE senza registro pubblico la partita IVA resta "da verificare a mano".
