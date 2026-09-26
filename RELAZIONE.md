# Relazione tecnica — Assistente AI per la gestione delle fatture

Alessandra Tafuro · settembre 2026

---

## 1. Obiettivo

Una piccola impresa riceve fatture fornitori da canali e formati diversi (foto, PDF, vocali, messaggi). L'obiettivo è un **assistente agentico** che le acquisisca da una chat, ne estragga i dati **con l'aiuto dell'utente**, le archivi in modo affidabile, le controlli e produca riepiloghi da inviare al commercialista.

Il sistema realizza tutte e otto le funzioni previste dai requisiti. Ciascuna è stata **verificata sul bot Telegram reale**, e la parte di estrazione anche con una valutazione automatica su un golden set (sezione 7).

| # | Funzione | Dove (codice) | Stato |
|---|---|---|---|
| 1 | Acquisizione multicanale (testo, foto, PDF, vocali) | `bot_telegram.py`, `trascrizione.py` | ✅ verificata sul bot |
| 2 | Estrazione assistita e bozze persistenti | `estrazione.py`, `bozze_fatture.py` | ✅ |
| 3 | Archiviazione su Drive privato e registrazione | `archivio.py`, `google_servizi.py`, `registro_fatture.py` | ✅ |
| 4 | Controlli contabili (centesimi, duplicati, IVA non ordinaria) | `fatture_comuni.py`, `registro_fatture.py`, `bozze_fatture.py` | ✅ |
| 5 | Ciclo di vita (pagata, annullamento logico) | `registro_fatture.py` | ✅ |
| 6 | Riepiloghi mensili, trimestrali, annuali | `registro_fatture.py` | ✅ |
| 7 | Invio al commercialista (XLSX + link privati) | `commercialista.py` | ✅ |
| 8 | Robustezza e avvisi configurabili | `avvisi.py` + gestione errori in tutti i moduli | ✅ |

---

## 2. Scelta dello strumento: LangChain

Tra n8n, LangChain e OpenAI Agents SDK ho scelto **LangChain** (Python, `create_agent`). I motivi:

- **Controllo sulla logica contabile.** Centesimi, duplicati, coerenza degli importi, annullamento logico e riepiloghi sono normali funzioni Python: esatte, ripetibili, leggibili e verificabili una per una. In un workflow visuale la stessa logica sarebbe sparsa tra nodi e più difficile da controllare.
- **Ciclo agentico pronto.** `create_agent` fornisce il ciclo "ragiona → sceglie un tool → osserva il risultato → ripete". Con i **middleware** l'ho potuto correggere dove serviva (sezione 8, punto 8).
- **Coerenza con il percorso di studio.** È il framework del modulo, e il progetto consolida output strutturato, tool, agenti e memoria.

**Compromesso riconosciuto:** n8n offre già pronti i nodi Telegram, Google Drive ed email; con LangChain le integrazioni le ho scritte a mano (`bot_telegram.py`, `google_servizi.py`). Il peso del lavoro si sposta sul codice, ma in cambio ho il pieno controllo della gestione degli errori, dei permessi minimi e delle conferme.

---

## 3. Architettura del sistema

```
Telegram ─> bot_telegram.py ─────────────── "centralinista", non intelligente
              handler: testo | foto | documento | vocale ─> trascrizione.py
              utenti autorizzati · file in dati/ricevuti · JobQueue (controllo scadenze)
                    │ messaggio + id della chat
                    ▼
            agente_fatture.py ───────────── create_agent (gpt-4.1-mini)
              system prompt con le regole · memoria per chat (checkpointer + thread_id)
              middleware: un tool alla volta · data di oggi sempre aggiornata
                    │ sceglie tra 15 tool (strumenti_fatture.py)
    ┌───────────────┼──────────────────┬───────────────────┬──────────────────┐
estrazione.py  bozze_fatture.py  registro_fatture.py   archivio.py      commercialista.py
PDF/foto/testo bozze, mancanti,  registro JSON,        originali su     XLSX + email con
→ dati         avvisi, proposta  pagamenti, annulli,   Google Drive     link privati
(LLM legge)    di scadenza       riepiloghi, scadenze       └── google_servizi.py (OAuth, Drive, Gmail)
                                                   avvisi.py: log, soglie, avvisi tecnici e contabili
```

### 3.1 Principio guida: *l'LLM legge, Python converte e conta*
L'LLM è bravo a **leggere** documenti eterogenei, ma nei calcoli e nelle trasformazioni non è affidabile. L'ho verificato più volte (sezione 8). Per questo:
- l'LLM copia importi e date **esattamente come sono scritti** ("1.200,00", "12/03/2025", "22 settembre 2026");
- Python converte gli importi in **centesimi interi** (con `Decimal`) e le date in `AAAA-MM-GG`, riconoscendo anche i mesi scritti in italiano;
- **tutti** i controlli, i totali e i calcoli sulle date sono in Python. Nel system prompt l'agente ha la regola esplicita di non fare calcoli e di non aggiungere controlli propri.

### 3.2 Acquisizione ed estrazione
| Canale | Come viene letto | Modello |
|---|---|---|
| PDF | testo estratto con `pypdf`, poi LLM | `gpt-4o-mini` |
| Foto JPEG/PNG | immagine in base64 all'LLM vision (`detail: high`) | `gpt-4.1-mini` |
| Vocale / audio | trascrizione (lingua it + prompt con il lessico delle fatture), poi come il testo | `gpt-4o-mini-transcribe` → `gpt-4o-mini` |
| Testo in chat | LLM sul messaggio | `gpt-4o-mini` |

- **Output strutturato:** schema Pydantic `DatiFattura` + `with_structured_output()`, `temperature=0`. Tutti i campi sono `Optional`: un campo vuoto è un **dato mancante da chiedere**, mai inventato. Le `description` dei campi sono istruzioni per l'LLM, per esempio "il fornitore, NON il cliente": ogni fattura di prova riporta anche la P.IVA del cliente.
- Tutti i canali restituiscono **lo stesso dizionario**, quindi il resto del sistema non dipende dal canale.
- I modelli sono stati **scelti misurando** sul golden set (sezione 8, punto 2).
- Il vocale trascritto viene **mostrato all'utente** ("Ho capito: …") prima di passare all'agente.

### 3.3 Bozze persistenti (estrazione assistita)
```
file / testo ──estrazione──> BOZZA (aperta) ──modifica──> … ──conferma──> REGISTRO + Drive
                                  └──────────────annulla──> non registrata (resta come "annullata")
```
- Una fattura **non entra mai direttamente nel registro**: prima diventa una bozza, salvata in `dati/bozze.json`, che sopravvive al riavvio del programma.
- A ogni modifica Python ricalcola: dati mancanti (gli 8 campi richiesti sono obbligatori), avvisi (coerenza importi, IVA non ordinaria, P.IVA diversa da 11 cifre, **possibile duplicato già in bozza**) e proposta di scadenza.
- **Scadenza mancante:** Python propone *data di emissione + 30 giorni*, indicata come "da confermare, non scritta sulla fattura". È l'utente a decidere.
- `modifica_bozza` riceve il valore come l'ha scritto l'utente; Python lo converte o lo rifiuta con un messaggio chiaro.
- `conferma_bozza` registra solo se non manca niente e non è un duplicato; subito dopo avvia l'archiviazione su Drive e il controllo della soglia d'importo.

### 3.4 L'agente
- **`create_agent` con `gpt-4.1-mini`.** Con 15 tool e una dozzina di regole serve un modello più attento di `gpt-4o-mini`.
- **System prompt:** le "regole del mestiere", ciascuna legata a un requisito o a un problema osservato:
  - mostrare sempre la bozza e chiedere i dati mancanti, uno o due alla volta;
  - registrare **solo dopo conferma esplicita**;
  - riportare gli avvisi dei tool senza aggiungerne di propri;
  - far verificare i vocali;
  - non fare calcoli;
  - cercare da sé l'id delle fatture;
  - chiedere conferma prima di annullare o di **inviare l'email** al commercialista, perché è un'azione irreversibile;
  - chiedere invece di indovinare se la richiesta è ambigua;
  - scrivere testo semplice adatto a Telegram.
- **Memoria:** `InMemorySaver` + `thread_id` = id della chat Telegram, così ogni utente ha la sua conversazione. Permette risposte come "sì, salvala" senza ripetere quale bozza.
- **Due memorie diverse**, scelta consapevole:
  - la conversazione è in RAM e si azzera al riavvio;
  - bozze e registro sono su file e sono persistenti. `/start` segnala le bozze rimaste in sospeso.
- **Middleware:**
  - `un_tool_alla_volta` imposta `parallel_tool_calls=False` (sezione 8, punto 8);
  - `data_sempre_aggiornata` ricostruisce il system prompt con la data di oggi a ogni chiamata, perché il bot può restare acceso più giorni.

### 3.5 Il bot Telegram
- `python-telegram-bot` v22 in modalità polling, con un **handler** per ogni tipo di messaggio e i comandi `/start`, `/stato` e `/controllo`.
- `asyncio.to_thread`: l'agente, sincrono e lento, gira in un thread separato e il bot resta reattivo ("sta scrivendo…").
- **Sicurezza:** risponde solo agli id in `TELEGRAM_UTENTI_AUTORIZZATI`. A un utente sconosciuto dice "non autorizzato" e ne mostra l'id, cosa utile al proprietario per la prima configurazione.
- Prima del download controlla il formato ammesso e il limite di 20 MB dei bot Telegram. I file vengono salvati con un nome unico (`idchat_idmessaggio_nome`).
- Il file Excel creato su richiesta viene inviato direttamente in chat.

### 3.6 Google Drive, Excel ed email
- **OAuth "App desktop"**, con un solo consenso per Drive e Gmail e **permessi minimi**:
  - `drive.file`: l'app vede solo i file creati da lei;
  - `gmail.send`: solo invio.

  Il token è salvato in `segreti/` e rinnovato automaticamente. Ho scelto l'API Gmail invece di SMTP con "password per le app": una sola configurazione e nessuna password salvata.
- **Archiviazione:** l'originale va nella cartella **privata** "Fatture - Assistente AI", con una sottocartella per anno.
  - Il nome del file è uniforme: `AAAA-MM-GG_Fornitore_Numero.ext`.
  - È archiviato l'originale di **ogni canale**: PDF, foto, file audio del vocale, e un `.txt` con il messaggio per le fatture scritte in chat.
- **Excel generato dal registro**, con 3 fogli:
  - *Riepilogo*: totali, quanto resta da pagare, casi IVA da verificare;
  - *Fatture*: con il link all'originale;
  - *Annullate*: con il motivo, perché lo storico non si nasconde al commercialista.

  Gli importi sono scritti come `Decimal(centesimi)/100`.
- **Email al commercialista:** Excel allegato ed elenco dei **link privati**. Ogni originale viene condiviso **in sola lettura solo con l'indirizzo del commercialista**, preso dal `.env`, e resta privato per chiunque altro. Le fatture senza originale vengono segnalate nel testo.

### 3.7 Robustezza e avvisi
- **Errori dell'utente** (file corrotto, PDF senza testo, foto non valida, formato non supportato, file inesistente): un messaggio chiaro con cosa fare, nessuna bozza e nessun avviso tecnico, perché non è un guasto. Le immagini sono controllate con la **firma dei byte** (JPEG `FF D8 FF`, PNG `89 50 4E 47`) **prima** di pagare una chiamata all'LLM.
- **Errori di sistema** (OpenAI, Drive o Gmail irraggiungibili): messaggio chiaro, riga nel log e conteggio per l'avviso tecnico.
- **Mai perdere dati:**
  - Drive giù → la fattura resta registrata, con archiviazione `in_attesa` e ripresa tramite `riprova_archiviazione`;
  - registro scritto in modo atomico (file temporaneo + rinomina) + **copia `.bak`** della versione precedente;
  - registro illeggibile → nessuna sovrascrittura, errore esplicito e avviso immediato.
- **Avvisi configurabili**: tutto sta nel `.env`, niente nel codice.
  - Canali (telegram, email) e destinatari.
  - **Soglia d'importo**, 5.000 € nel mio `.env`.
  - **Controllo giornaliero delle scadenze** alle 09:00 con 7 giorni di anticipo, tramite la JobQueue.
  - **Avviso tecnico** dopo 3 errori dello stesso servizio in 15 minuti, poi **pausa di 60 minuti** anti-raffica.

  Gli avvisi Telegram partono con una richiesta HTTP diretta, quindi funzionano anche fuori dal bot. Un avviso fallito finisce solo nel log e non genera un "avviso sull'avviso".

---

## 4. Tool definiti

**Due livelli.** La logica sta in moduli Python puri, senza LLM. I tool (`@tool` in `strumenti_fatture.py`) sono solo "maniglie" che l'agente può afferrare. Dell'agente l'LLM vede nome, docstring e tipi dei parametri: la **docstring dice quando usare il tool**, e `Literal` limita i valori ammessi.

| Tool | Cosa fa | Parametri |
|---|---|---|
| **Acquisizione e bozze** | | |
| `acquisisci_fattura_da_file` | PDF o foto → estrazione → nuova bozza | percorso_file |
| `acquisisci_fattura_da_testo` | testo scritto o vocale trascritto → nuova bozza (archivia l'audio o il testo come originale) | testo, percorso_audio |
| `mostra_bozza` | dati, mancanti, avvisi, proposta di scadenza | id_bozza |
| `elenca_bozze_aperte` | bozze in sospeso, anche di sessioni precedenti | — |
| `modifica_bozza` | completa o corregge un campo; la conversione la fa Python | id_bozza, campo (Literal), valore |
| `conferma_bozza` | registra, archivia su Drive, controlla la soglia — solo dopo conferma | id_bozza |
| `annulla_bozza` | scarta la bozza senza registrarla | id_bozza |
| **Registro** | | |
| `cerca_fatture` | per fornitore, numero e stato; serve anche a trovare l'id | testo, stato |
| `segna_pagata` | stato → pagata, con data | id_fattura, data_pagamento |
| `annulla_fattura` | annullamento logico con motivo | id_fattura, motivo |
| `riepilogo` | totali del periodo, da pagare, per fornitore, IVA da verificare | tipo (mese/trimestre/anno), anno, numero |
| `fatture_in_scadenza` | in scadenza entro N giorni + scadute + senza data | entro_giorni, data_riferimento |
| **Google e commercialista** | | |
| `esporta_riepilogo_excel` | crea l'XLSX del periodo; il bot lo manda in chat | tipo, anno, numero |
| `invia_riepilogo_al_commercialista` | email con XLSX e link privati — solo dopo conferma | tipo, anno, numero |
| `riprova_archiviazione` | ricarica su Drive gli originali rimasti in attesa | — |

**Verifiche del function calling.** Una prima prova con `bind_tools`, senza il ciclo dell'agente, ha mostrato che:
- "Quanto ho speso nel terzo trimestre?" produce `riepilogo(trimestre, 2026, 3)`, con l'anno ricavato dalla data nel prompt;
- "Ciao, come stai?" non chiama nessun tool;
- "Ho pagato la fattura di Beta Logistica" produce `cerca_fatture(testo="Beta Logistica", stato="da_pagare")` e **non** `segna_pagata`. L'LLM non conosce l'id e la docstring dice di cercarlo prima; il filtro "da_pagare" l'ha dedotto da solo.

È la prova che le docstring guidano la scelta del tool. Con il ciclo dell'agente la stessa frase arriva fino in fondo: `cerca_fatture` → `segna_pagata`.

---

## 5. Stato di pagamento e annullamento logico

Ogni fattura nel registro ha due informazioni **indipendenti**:

| Campo | Valori | Significato |
|---|---|---|
| `stato_pagamento` (+ `data_pagamento`) | `da_pagare` → `pagata` | se e quando è stata pagata |
| `annullata` (+ `motivo_annullamento`) | `false` → `true` | se è stata annullata e perché |

- Ogni fattura nasce `da_pagare` e non annullata.
- **Annullamento logico:** il record **non viene mai cancellato**. `annullata = true` e il motivo vengono salvati. La fattura esce da riepiloghi, totali, scadenze ed elenco da pagare, ma resta nello storico (`cerca_fatture(stato="annullata")`) e nel foglio "Annullate" dell'Excel. Si può sempre ricostruire cosa è successo e perché.
- **Regole di transizione:**
  - pagata → annullata: **permesso** (es. rimborso o nota di credito, e lo storico conserva entrambe le informazioni);
  - annullata → pagata: **bloccato** ("la fattura è annullata: non si può segnare come pagata").
- Anche le fatture annullate contano per il **controllo duplicati**: se la stessa fattura riarriva, viene segnalata.
- L'agente chiede conferma prima di annullare una fattura registrata.
- **Verificato:**
  - una fattura annullata sparisce dal riepilogo del trimestre ma resta nello storico;
  - entrambe le regole di transizione sono state provate in un senso e nell'altro;
  - sul bot, "Ho pagato la fattura della Tipografia Rapida oggi" → ricerca + pagamento, senza chiedere l'id.

**Duplicati.** Stessa fattura = stesso fornitore + stesso numero. Il fornitore si riconosce dalla **P.IVA**, più affidabile del nome: "Alfa Forniture SRL" e "ALFA FORNITURE S.R.L." sono lo stesso fornitore. Il nome si usa solo se la P.IVA manca. I duplicati sono segnalati già nella bozza e bloccati alla conferma.

---

## 6. Data di riferimento

Le fatture di prova hanno date del 2025 (le foto) e del 2026 (i PDF).
- **Nelle prove automatiche** ho usato la data fissa **25/09/2026**, così i risultati sono ripetibili.
- **Nel bot reale** si usa la **data di oggi**, passata all'agente nel system prompt a ogni chiamata, perché l'LLM da solo non sa che giorno è.

Per questo le tre foto del 2025 risultano "scadute da oltre 16 mesi": è corretto, dipende dal materiale di prova.

---

## 7. Valutazione dell'estrazione

- **Golden set:** `valutazione/golden_set.json`, **14 fatture** con i dati attesi verificati a mano: 9 PDF (template diversi, due con IVA non ordinaria), 3 foto da telefono, 1 vocale e 1 messaggio di testo.
- **Metodo:** `codice/valuta_golden_set.py` esegue **la stessa estrazione del bot** per ciascun canale e confronta i **9 campi**. Una fattura è corretta solo se sono giusti **tutti** i campi. La valutazione è **ripetuta 3 volte**, perché un solo giro giusto non dimostra la stabilità.
- **Risultato finale: 42 estrazioni corrette su 42 (100%).** Il report completo è in `valutazione/VALUTAZIONE.md`.

| Canale | Fatture | Estrazioni | Corrette |
|---|---|---|---|
| PDF | 9 | 27 | 27 |
| Foto | 3 | 9 | 9 |
| Vocale | 1 | 3 | 3 |
| Testo | 1 | 3 | 3 |
| **Totale** | **14** | **42** | **42** |

- **Casi IVA non ordinari riconosciuti:**
  - fattura 2026/060, inversione contabile;
  - fattura 2026/062, aliquota ridotta del 10%.
- **Criterio sul fornitore:** il confronto ignora punteggiatura e maiuscole della forma societaria ("S.r.l." = "SRL"). Un errore di lettere, come "Cartoneria" al posto di "Cartoleria", resta un errore.

**Il vocale.** Il vocale di prova l'ho registrato **con la mia voce direttamente in Telegram**, dettando i dati di una fattura inventata (Cartoleria Bianchi). Il bot lo ha trascritto parola per parola e l'ha registrato dopo la conferma. Nel repository, per non pubblicare la mia voce, c'è una **versione sintetica** con gli stessi dati, generata con `gpt-4o-mini-tts`. Tutta la procedura è documentata in `file_di_prova/vocale/COME_E_STATO_CREATO.md`.

Il percorso per arrivare al 100% fa parte dei risultati:

| Versione del vocale | Corrette | Cosa è successo |
|---|---|---|
| reale, la mia voce | 2/3 | in un giro la P.IVA è stata trascritta con 12 cifre |
| sintetico, P.IVA scritta come numero | 0/3 | la voce legge a gruppi ("zero undici ventidue…") → `011222334455` |
| sintetico, P.IVA dettata cifra per cifra | 3/3 | — |

→ I **numeri lunghi dettati a voce sono il punto debole del canale vocale**. Nel flusso reale l'errore viene comunque intercettato: il controllo Python segnala "P.IVA non valida: 12 cifre" e l'utente la corregge nella bozza. Il bot consiglia di dettare P.IVA e numeri cifra per cifra.

---

## 8. Limiti osservati e soluzioni adottate

1. **L'LLM sbaglia le conversioni di date.** Chiedendogli direttamente il formato `AAAA-MM-GG`, su una foto ha letto "12/03/2025" e scritto "2023-03-12".
   → L'LLM copia la data come scritta, Python la converte. È da qui che nasce il principio "l'LLM legge, Python converte e conta".

2. **La lettura delle immagini non è perfettamente ripetibile.** Con `temperature=0`, 3 giri × 3 foto:
   - `gpt-4o-mini`: 8/9, perché una volta ha letto la P.IVA `03876541203` come `03767541203`;
   - `gpt-4.1-mini`: 9/9;
   - `gpt-4o`: 9/9, ma più costoso.

   → Per le foto ho scelto `gpt-4.1-mini`. Il modello si sceglie **misurando più volte**, non fidandosi di un singolo test.

3. **Scadenza non scritta** ("30 gg df" sulla foto Elettroimpianti Verdi). L'LLM **non** calcola la data, perché "30 gg df" può voler dire data fattura o fine mese, e una scadenza sbagliata ha conseguenze reali.
   → Il campo resta vuoto. Python propone emissione + 30 giorni e l'utente conferma o corregge. Verificato sul flusso completo: proposta dell'11/04/2025 → "sì va bene" → registrata.

4. **Chiamate ai tool in parallelo (il problema più serio).** Alla frase "Scade il 20 ottobre. Poi salvala pure." l'agente ha lanciato `modifica_bozza` e `conferma_bozza` **nello stesso istante**. La conferma è partita prima della modifica ed è stata rifiutata perché mancava la scadenza. C'era anche il rischio che due scritture contemporanee sullo stesso file JSON si sovrascrivessero. In un'altra prova l'LLM aveva chiesto due volte lo stesso tool in parallelo.
   → Middleware `un_tool_alla_volta` con `parallel_tool_calls=False`. Dopo la correzione modifica e conferma avvengono in sequenza e la fattura viene registrata.

5. **L'agente chiedeva l'id all'utente.** Con "Ho pagato la fattura di Beta Logistica" rispondeva "mi serve l'id della fattura".
   → Regola del prompt resa esplicita: "non chiederlo all'utente, cercalo tu; se ne trovi più di una, chiedi quale". Dopo la correzione: `cerca_fatture` → `segna_pagata` in automatico.

6. **L'LLM "controlla" male.** Sulla bozza del vocale l'agente ha aggiunto di sua iniziativa "la partita IVA sembra lunga". Era falso: aveva esattamente 11 cifre.
   → Controllo della lunghezza della P.IVA in Python, più la regola del prompt "riporta solo gli avvisi dei tool, non aggiungere controlli tuoi". Lo stesso motivo per cui i totali non li fa l'LLM: non conta in modo affidabile.

7. **Date dette a voce.** "22 settembre 2026" veniva copiato così com'era e Python lo scartava, lasciando la data vuota.
   → `normalizza_data` riconosce anche i mesi in italiano.

8. **Numeri dettati a voce** (vedi sezione 7). → Controllo Python sulle 11 cifre, verifica obbligatoria della bozza, e il consiglio di dettare cifra per cifra.

9. **Foto compresse da Telegram.** Inviata come "foto", l'immagine viene ridimensionata: 137 KB contro i 249 KB dell'originale. Nella prova è stata letta comunque in modo corretto, ma per i numeri piccoli è un rischio.
   → Il bot consiglia di inviare le foto come *file*.

10. **Ambiguità del linguaggio.** Una frase come "a chi ho dato di più" può voler dire "pagato" o "fatturato".
    → Regola del prompt: nel dubbio chiedere invece di indovinare.

11. **Limiti ancora aperti:**
    - le partite IVA di prova sono fittizie e non superano la cifra di controllo ufficiale. Con fatture reali si potrebbe aggiungere quel controllo;
    - la memoria della conversazione si azzera al riavvio del bot (bozze e registro no). Un checkpointer su database la renderebbe persistente;
    - l'app Google è in modalità test (avviso "app non verificata"; gli utenti vanno aggiunti a mano);
    - il registro in JSON è adatto a una piccola impresa e a un solo processo. Con più utenti in contemporanea servirebbe un database;
    - i PDF scansionati, cioè senza testo, vanno inviati come foto: non c'è ancora una conversione automatica da PDF a immagine.

---

## 9. Sicurezza e privacy

- Nessun segreto nel codice né nel repository. Token Telegram, chiave OpenAI e credenziali Google stanno in `.env` e in `segreti/`, esclusi da `.gitignore`. Nel repository c'è solo `.env.example`. Prima della pubblicazione i file sono stati controllati automaticamente per cercare token e dati personali.
- Il bot è limitato agli utenti autorizzati.
- I file su Drive sono privati e condivisi in sola lettura solo con il commercialista. I permessi Google sono i minimi necessari.
- Le azioni irreversibili (registrazione, annullamento, invio email) avvengono solo dopo conferma esplicita.
- I dati personali di prova sono stati tolti dal registro di esempio (percorsi locali, id dei file Drive). Il vocale pubblicato è sintetico.
