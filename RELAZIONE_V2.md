# Relazione tecnica — Versione 2

Alessandra Tafuro · settembre 2026

La v1 (`codice/`, tag `v1-consegna`, descritta in [RELAZIONE.md](RELAZIONE.md)) è un assistente completo e funzionante: un **agente** `create_agent` che gestisce tutto, comprese le bozze delle fatture, guidato da system prompt e middleware.

La v2 (`codice_v2/`) nasce da una domanda precisa: **quali decisioni conviene lasciare all'LLM e quali no?** Mantiene tutte le funzioni della v1, ne riusa i moduli e cambia l'**architettura**:

| | v1 | v2 |
|---|---|---|
| Percorso delle bozze | l'agente decide quando chiedere, modificare, confermare | **grafo LangGraph**: il percorso è scritto nel codice |
| Ruolo dell'LLM nelle bozze | decide la strada, chiama i tool, legge la fattura | **legge** la fattura e **interpreta** le risposte; non sceglie mai la strada |
| Stato di una bozza a metà | bozza su file, conversazione in RAM | tutto su **SQLite** (checkpointer del grafo) |
| Accesso al registro | tool interni all'agente | **server MCP in sola lettura** + tool di scrittura locali |
| Contenuto delle fatture | non interrogabile | **RAG** |
| Instradamento dei messaggi | tutto all'agente | **router**: fattura nuova → grafo, resto → agente |

---

## 1. Architettura

```
Telegram ─> bot_telegram_v2.py (riusa handler, download, trascrizione, comandi e avvisi della v1)
               │
               ├─ c'è una domanda del grafo in sospeso? ──────> grafo_bozze.rispondi()  (Command(resume=...))
               ├─ foto / PDF / vocale ─────────────────────────> grafo_bozze.avvia()
               └─ testo ─> ROUTER (LLM: "è una fattura nuova?")
                              ├─ sì ─> grafo_bozze.avvia()
                              └─ no ─> agente_v2 (create_agent)
                                          ├─ tool di LETTURA  ── via MCP ──> server_mcp.py ──> registro
                                          ├─ RAG sul contenuto ─────────────> rag_fatture.py
                                          └─ tool di SCRITTURA (locali, v1): paga, annulla, Excel, email

grafo_bozze.py:
  START → estrai → controlla ─(manca un dato)→ chiedi_mancante ─→ controlla  (ciclo)
                      └─(completa)→ chiedi_conferma ─(correzione)→ controlla
                                         ├─(annulla)→ annulla → END
                                         ├─(conferma, < soglia)→ registra → END
                                         └─(conferma, ≥ soglia)→ doppia_conferma → registra / annulla
```

| File | Ruolo |
|---|---|
| `percorsi_v2.py` | collega i moduli della v1 e definisce i file della v2 in `dati/` |
| `grafo_bozze.py` | il percorso delle bozze come grafo, con `interrupt` e `SqliteSaver` |
| `agente_v2.py` | agente per le richieste libere (tool MCP + RAG + scrittura locale) e router |
| `server_mcp.py` | server MCP del registro, sola lettura: 4 tool + 1 risorsa |
| `rag_fatture.py` | RAG sul testo completo delle fatture registrate |
| `bot_telegram_v2.py` | bot: cambia solo lo smistamento rispetto alla v1 |
| `confronto_v1_v2.py` | confronto misurato tra le due versioni |

### 1.1 Il grafo delle bozze
- **I controlli sono quelli della v1** (`bozze_fatture._aggiorna_controlli`): dati mancanti, coerenza degli importi, P.IVA di 11 cifre, IVA non ordinaria, possibile duplicato, proposta di scadenza (emissione + 30 giorni). Cambia solo **chi decide il percorso**.
- **`interrupt()`**: il grafo si ferma per chiedere un dato o una conferma; la risposta dell'utente lo fa ripartire con `Command(resume=...)`.
- **`SqliteSaver`**: lo stato del grafo è su disco (`dati/v2_grafo_bozze.sqlite`). Una domanda resta in sospeso anche dopo un riavvio del bot, e `/start` la ripropone.
- **L'LLM interpreta, Python decide.** La risposta dell'utente ("va bene la data che proponi", "no aspetta, la scadenza è il 30 ottobre") viene interpretata da un LLM con output strutturato in *conferma / annulla / valore*, con campo e valore **copiati come scritti**. Python converte il valore (centesimi, date) e sceglie il ramo del grafo. Le risposte ovvie ("sì", "annulla") non chiamano l'LLM.
- **Doppia conferma** sopra una soglia configurabile (`DOPPIA_CONFERMA_EURO`, 5.000 €): è un nodo del grafo, quindi **non si può saltare**.
- Una fattura alla volta per chat: se ne arriva un'altra mentre il grafo aspetta una risposta, il bot chiede di concludere prima quella in corso.

### 1.2 Server MCP in sola lettura
`server_mcp.py` (FastMCP, stdio) espone `cerca_fatture`, `riepilogo`, `fatture_in_scadenza`, `fornitore_piu_costoso` e la risorsa `fatture://fornitori`. L'agente li riceve con `MultiServerMCPClient` e li scopre all'avvio (**discovery**). Pagare, annullare e inviare email restano **tool locali**, fuori dal server: un server MCP può essere collegato a client che non controlliamo, e la protezione vera è **non esporre l'azione**, senza affidarsi al prompt. Lo stesso server è collegabile a Claude Desktop o Claude Code senza modifiche.

### 1.3 RAG
Il testo completo di ogni fattura registrata si ricava dall'**originale**, calcolato una volta e tenuto in cache in `dati/v2_rag_testi.json`:
- PDF → pypdf;
- foto → trascrizione vision;
- vocale → trascrizione audio;
- testo → letto così com'è.

Embedding `text-embedding-3-small` e `InMemoryVectorStore`. L'indice si costruisce al primo uso e **si aggiorna** quando il grafo registra una fattura. Le domande qualitative ("chi mi ha venduto il toner?") vanno al RAG; quelle quantitative (quanto, è pagata?) ai tool del registro.

### 1.4 Router
Un LLM piccolo, con output strutturato `nuova_fattura: bool`, decide se un messaggio di testo descrive una fattura da registrare o è una richiesta. File e vocali vanno direttamente al grafo, tranne i vocali che rispondono a una domanda in sospeso.

---

## 2. Confronto misurato

`python codice_v2/confronto_v1_v2.py 3`: **7 scenari × 2 versioni × 3 giri**, con gli stessi messaggi dell'utente e su dati temporanei (Drive, avvisi e RAG disattivati). Un'esecuzione è **corretta** se il **registro finale** è quello atteso: non conta la risposta a parole. Risultati completi: [`valutazione/CONFRONTO_V1_V2.md`](valutazione/CONFRONTO_V1_V2.md).

| Scenario | Corretti v1 | Corretti v2 | Chiamate LLM v1 / v2 | Token v1 / v2 |
|---|---|---|---|---|
| 1. Fattura completa + conferma | 3/3 | 3/3 | 6,3 / 2,0 | 15.692 / 1.236 |
| 2. Scadenza mancante, risposta e conferma nello stesso messaggio | 3/3 | 3/3 | 7,0 / 2,0 | 18.181 / 1.161 |
| 3. **Riavvio del programma a metà bozza** | **0/3** | **3/3** | 6,0 / 3,0 | 13.614 / 1.578 |
| 4. Duplicato | 3/3 | 3/3 | 6,7 / 2,0 | 17.025 / 1.268 |
| 5. Importo sopra 5.000 € | 3/3 | 3/3 | 6,0 / 2,0 | 15.031 / 1.250 |
| 6. L'utente rinuncia | 3/3 | 3/3 | 5,0 / 2,0 | 11.734 / 1.239 |
| 7. Nessuna conferma data (sicurezza) | 3/3 | 3/3 | 3,0 / 1,0 | 6.133 / 815 |
| **Totale** | **18/21** | **21/21** | **5,7 / 2,0** | **13.916 / 1.221** |

Tempo medio per scenario: v1 5,7 s, v2 1,8 s. Doppia conferma sopra 5.000 €: v1 0/3, v2 3/3.

### 2.0 Verifica dal vivo su Telegram (27/09/2026)
| Prova | Esito |
|---|---|
| Fattura scritta senza scadenza → il grafo propone emissione + 30 giorni e si ferma | ✅ |
| **Bot spento e riacceso** con la domanda in sospeso → `/start` ripropone la stessa domanda | ✅ |
| "va bene la data che proponi" → riepilogo → "sì registrala" → registrata (F0017) e originale archiviato su Drive | ✅ |
| "chi mi ha venduto il toner?" (RAG) → Alfa Forniture SRL, fattura 2026/037 | ✅ |
| "quali fatture scadono nei prossimi 30 giorni?" (server MCP) → elenco corretto, compresa la fattura appena registrata | ✅ |

### 2.1 Cosa dicono i numeri
- **Affidabilità (scenario 3).** Dopo un riavvio la v1 ha ancora la bozza su file, ma ha perso la conversazione. A "va bene la data che proponi" risponde: *"Quale fattura o bozza stai aggiornando?"*. La v2 riprende esattamente dalla domanda in sospeso. Nella v1 l'utente può recuperare con `/start`, che mostra le bozze aperte, ma servono passaggi in più.
- **Costo (circa 11 volte meno token).** A ogni passo l'agente v1 rimanda al modello system prompt, 15 schemi di tool e tutta la conversazione. Nel grafo della v2 l'LLM fa solo due lavori piccoli e mirati: leggere la fattura e interpretare una risposta. È anche **circa 3 volte più veloce**.
- **Regole garantite.** La doppia conferma nella v2 è un **nodo del grafo**: avviene 3 volte su 3 e non dipende da quanto il modello "ubbidisce" al prompt. Nella v1 non esiste, e per aggiungerla bisognerebbe chiederla nel prompt, senza garanzie.
- **Il bug delle chiamate in parallelo della v1** (modifica e conferma nello stesso istante, RELAZIONE.md, limiti osservati punto 4) nella v2 non può verificarsi per costruzione: i passi sono sequenziali per definizione del grafo, non grazie a un middleware.

### 2.2 Dove la v2 NON è migliore (compromessi)
- **Più rigida.** Nello scenario 2 l'utente scrive in un solo messaggio *"Scade il 20 ottobre. Poi salvala pure."*. La v2 applica la data ma chiede comunque la conferma finale, con un messaggio in più. L'agente v1 gestisce frasi composte con più naturalezza. È il prezzo della prevedibilità: in contabilità lo ritengo accettabile, in un assistente conversazionale generico forse no.
- **Più parti in movimento.** Router, grafo, agente, server MCP, due database SQLite: più file da capire e mantenere. Per una piccola impresa con un solo utente, la v1 resta una soluzione valida e più semplice.
- **Il router è un punto di errore nuovo.** Se classifica male un messaggio di testo, una domanda può finire nel grafo o una fattura all'agente. Mitigazioni:
  - l'agente v2 sa che le fatture nuove non le registra lui, e invita a mandarle;
  - un file o un vocale non passano mai dal router.
- **Server MCP via stdio:** ogni chiamata a un tool di lettura avvia il processo del server, che è più lento di un tool interno. Per un uso intenso converrebbe il server in modalità HTTP, sempre acceso.

---

## 3. Limiti e sviluppi possibili
- Il **RAG** è in memoria: si ricostruisce all'avvio a partire dalla cache dei testi. Con molte fatture converrebbe un vector store persistente, come Chroma.
- Nella v2 le **correzioni** in fase di conferma si fanno un campo alla volta.
- I pattern **Reflection** (per il testo dell'email al commercialista) e **Tree of Thoughts** sono stati studiati ma **non inseriti**. La Reflection richiede controlli oggettivi in Python per essere utile, perché l'LLM che rilegge se stesso è indulgente. Il Tree of Thoughts moltiplica il costo senza un problema del progetto che lo giustifichi.
- **Per un uso in produzione** mancano ancora: container Docker, test automatici in CI (GitHub Actions) che eseguano confronto e golden set a ogni modifica, tracciamento delle chiamate (LangSmith) e un database al posto del registro JSON.
