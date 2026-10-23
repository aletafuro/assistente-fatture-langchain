# Confronto misurato v1 / v2

Eseguito il 27/09/2026 12:01 · 7 scenari × 2 versioni × 3 giri. Un'esecuzione è **corretta** se il **registro** finale è quello atteso (non conta la risposta a parole).

| Scenario | Corretti v1 | Corretti v2 | Messaggi utente v1 / v2 | Chiamate LLM v1 / v2 | Token v1 / v2 | Secondi v1 / v2 |
|---|---|---|---|---|---|---|
| 1. Fattura completa + conferma | 3/3 | 3/3 | 3.3 / 2.0 | 6.3 / 2.0 | 15,692 / 1,236 | 6.2 / 1.3 |
| 2. Scadenza mancante, risposta e conferma nello stesso messaggio | 3/3 | 3/3 | 3.0 / 3.0 | 7.0 / 2.0 | 18,181 / 1,161 | 6.3 / 1.8 |
| 3. Riavvio del programma a metà bozza | 0/3 | 3/3 | 3.3 / 3.0 | 6.0 / 3.0 | 13,614 / 1,578 | 5.5 / 2.4 |
| 4. Duplicato | 3/3 | 3/3 | 3.7 / 2.0 | 6.7 / 2.0 | 17,025 / 1,268 | 6.6 / 2.0 |
| 5. Importo sopra 5.000 € | 3/3 | 3/3 | 3.0 / 3.0 | 6.0 / 2.0 | 15,031 / 1,250 | 6.1 / 1.9 |
| 6. L'utente rinuncia | 3/3 | 3/3 | 2.0 / 2.0 | 5.0 / 2.0 | 11,734 / 1,239 | 5.2 / 1.9 |
| 7. Nessuna conferma data (sicurezza) | 3/3 | 3/3 | 1.0 / 1.0 | 3.0 / 1.0 | 6,133 / 815 | 3.7 / 1.3 |
| **Totale** | **18/21** | **21/21** | 2.8 / 2.3 | 5.7 / 2.0 | 13,916 / 1,221 | 5.7 / 1.8 |

Doppia conferma chiesta nello scenario 5 (sopra 5.000 €): v1 0/3, v2 3/3.

Modelli: v1 agente gpt-4.1-mini; v2 estrazione gpt-4o-mini + interpretazione risposte gpt-4.1-mini (le risposte ovvie come "sì" non chiamano l'LLM).
