# Foto di fatture reali — dati attesi (per autoverifica)

Tre fotografie di fatture reali (fornitori e template diversi), da usare come input di
prova per il **canale immagini** dell'assistente. L'assistente deve acquisirle ed
estrarne i dati da zero.

Qui sotto i dati attesi dall'estrazione, per verificare l'accuratezza. Tutte e tre sono a
IVA ordinaria 22% e contabilmente coerenti (imponibile + IVA = totale).

## `foto-fattura-officina-digitale.jpg`

- **Fornitore**: Officina Digitale S.r.l. — Via delle Idee 12, 40125 Bologna (BO)
- **P. IVA / C.F.**: 12345678901 / 12345678901
- **Cliente**: VerdeCasa S.n.c. — Via dei Tigli 8, 20122 Milano (MI) — P. IVA 98765432109
- **Numero**: FAT/2025/0048
- **Data emissione**: 14/04/2025 · **Data scadenza**: 14/05/2025
- **Condizioni**: bonifico bancario 30 gg
- **Righe**:
  - Consulenza strategica — 8 × 75,00 = 600,00
  - Sviluppo sito web — 40 × 65,00 = 2.600,00
  - Integrazione CMS — 8 × 60,00 = 480,00
  - Formazione — 4 × 70,00 = 280,00
- **Subtotale / imponibile**: 3.960,00 € · **IVA 22%**: 871,20 € · **Totale**: 4.831,20 €
- **IBAN**: IT32 X053 8702 4010 0000 1234 567 (BPER Banca S.p.A.)

## `foto-fattura-studio-bianchi.jpg`

- **Fornitore**: Studio Creativo Bianchi — Via delle Arti 12, 40126 Bologna (BO)
- **P. IVA**: 03876541203
- **Cliente**: VerdeVivo S.r.l. — Via Nazionale 45, 50123 Firenze (FI) — P. IVA 06123450987
- **Numero**: FAT-2025-014
- **Data emissione**: 12/03/2025 · **Data scadenza**: 11/04/2025
- **Righe**:
  - Progettazione grafica campagna social — 1 × 800,00 = 800,00
  - Realizzazione contenuti visivi — 1 × 600,00 = 600,00
  - Consulenza strategica — 1 × 400,00 = 400,00
- **Imponibile**: 1.800,00 € · **IVA 22%**: 396,00 € · **Totale**: 2.196,00 €
- **IBAN**: IT60 X030 6902 4010 0000 0123 456 · Causale FAT-2025-014

## `foto-fattura-elettroimpianti-verdi.jpg`

- **Fornitore**: Elettroimpianti Verdi S.r.l. — Via delle Industrie 24, 35129 Padova (PD)
- **P. IVA / C.F.**: 05231470968 / 05231470968 · Tel 049 8203941
- **Cliente**: Edilizia Rossi S.p.A. — Via Roma 112, 36077 Altavilla Vicentina (VI) — P. IVA 04128730245
- **Numero**: FAT-2025-0147 · **Codice cliente**: CLI-0089
- **Data**: 12/03/2025 · **Modalità**: bonifico bancario 30 gg df
- **Righe** (IVA 22% per riga):
  - Quadro elettrico di distribuzione 24 moduli — 2 × 180,00 = 360,00
  - Interruttore magnetotermico differenziale — 6 × 45,00 = 270,00
  - Cavo FG16 3x2,5 mm² (rotolo 100 m) — 3 × 95,00 = 285,00
  - Installazione e collaudo impianto — 1 × 600,00 = 600,00
  - Sopralluogo tecnico — 1 × 120,00 = 120,00
- **Imponibile**: 1.635,00 € · **IVA 22%**: 359,70 € · **Totale documento**: 1.994,70 €
- **IBAN**: IT60 X030 6912 3456 7890 1234 567 (Intesa Sanpaolo S.p.A.) · BIC BCITITMM

> Nota: nella foto di Elettroimpianti Verdi le righe della tabella appaiono leggermente
> disallineate rispetto alle quantità — è un caso realistico che mette alla prova
> l'estrazione tabellare.
