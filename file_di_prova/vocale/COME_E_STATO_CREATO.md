# Il messaggio vocale di prova

Tra i file di prova non c'era un audio: l'ho prodotto io, e qui documento come.

## Test sul bot reale
Durante lo sviluppo ho registrato **un vocale con la mia voce direttamente in Telegram** (tenendo premuto il microfono), dettando i dati di una fattura inventata:

> "Fattura della Cartoleria Bianchi srl, partita IVA 01122334455, numero 45 del 24 settembre 2026, scadenza 24 ottobre 2026, imponibile 200 euro, IVA 44 euro, totale 244 euro."

Il bot lo ha trascritto parola per parola, ha creato la bozza con tutti i dati corretti e, dopo la conferma, l'ha registrato (F0015 nel registro di esempio) e archiviato su Google Drive.

## Il file in questa cartella
Per **non pubblicare la mia voce** nel repository, `vocale-cartoleria-bianchi.ogg` è una versione **sintetica** con gli stessi dati, generata con la sintesi vocale di OpenAI:

- modello: `gpt-4o-mini-tts`, voce `alloy`
- formato: OGG/Opus, lo stesso usato dai vocali di Telegram
- istruzione di stile: parlare in italiano con tono naturale, come chi detta una fattura al telefono, leggendo la partita IVA una cifra alla volta
- testo: "Fattura della Cartoleria Bianchi srl, partita IVA: zero, uno, uno, due, due, tre, tre, quattro, quattro, cinque, cinque. Numero 45 del 24 settembre 2026, scadenza 24 ottobre 2026, imponibile 200 euro, IVA 44 euro, totale 244 euro."

Nota: una prima versione sintetica con la partita IVA scritta come numero ("01122334455") veniva letta dalla voce a gruppi di cifre, e la trascrizione produceva `011222334455` (12 cifre) in 3 giri su 3. Dettata cifra per cifra, come fa una persona reale, la trascrizione è corretta in 3 giri su 3.

Viene usato dalla valutazione (`python codice/valuta_golden_set.py`) come fattura del canale "vocale" del golden set. Il percorso è lo stesso del bot: trascrizione con `gpt-4o-mini-transcribe`, poi estrazione come un messaggio di testo.
