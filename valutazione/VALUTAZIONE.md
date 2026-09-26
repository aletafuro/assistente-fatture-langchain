# Valutazione dell'estrazione — golden set

Eseguita il 26/09/2026 11:21 · 14 fatture · 3 giri · 42 estrazioni · durata 0.9 minuti.
Una fattura è **corretta** solo se **tutti i 9 campi** coincidono con i dati attesi (fornitore, partita IVA, numero, data emissione, data scadenza, imponibile, IVA, totale, regime IVA).

## Risultato per canale

| Canale | Fatture | Estrazioni | Corrette | Percentuale |
|---|---|---|---|---|
| PDF | 9 | 27 | 27 | 100% |
| Foto | 3 | 9 | 9 | 100% |
| Vocale | 1 | 3 | 3 | 100% |
| Testo | 1 | 3 | 3 | 100% |
| **Totale** | **14** | **42** | **42** | **100%** |

## Dettaglio per fattura

| File | Canale | Giro 1 | Giro 2 | Giro 3 |
|---|---|---|---|---|
| fattura-2026-037.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-039.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-041.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-044.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-046.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-056.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-058.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-060.pdf | PDF | ✅ | ✅ | ✅ |
| fattura-2026-062.pdf | PDF | ✅ | ✅ | ✅ |
| foto-fattura-officina-digitale.jpg | Foto | ✅ | ✅ | ✅ |
| foto-fattura-studio-bianchi.jpg | Foto | ✅ | ✅ | ✅ |
| foto-fattura-elettroimpianti-verdi.jpg | Foto | ✅ | ✅ | ✅ |
| vocale-cartoleria-bianchi.ogg | Vocale | ✅ | ✅ | ✅ |
| testo-ottica-visione.txt | Testo | ✅ | ✅ | ✅ |

## Errori per campo

Nessun errore su nessun campo.

## Modelli usati

- PDF e testo: `gpt-4o-mini` (temperature 0) con output strutturato Pydantic
- Foto: `gpt-4.1-mini` (temperature 0), immagine in base64 con `detail: high`
- Vocale: trascrizione `gpt-4o-mini-transcribe` (lingua it), poi estrazione come il testo
- Conversioni (centesimi, date) e controlli: Python
