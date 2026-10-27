# Valutazione del RAG (2026-10-27)

Indice: `InMemoryVectorStore` · K = 4 · risposta: gpt-4.1-mini · giudice RAGAS: gpt-4.1-mini · 16 domande

| Ricerca: hit@K | recall@K | MRR | llm_context_precision_with_reference | context_recall | faithfulness | factual_correctness | answer_relevancy |
|---|---|---|---|---|---|---|---|
| 1.0 | 1.0 | 0.922 | 0.865 | 1.0 | 0.946 | 0.611 | 0.776 |

| Domanda | Attese | Trovate | llm_context_precision_with_reference | context_recall | faithfulness | factual_correctness | answer_relevancy |
|---|---|---|---|---|---|---|---|
| Chi ci ha venduto il toner? | F0001 | F0001, F0010, F0015, F0012 | 1.0 | 1.0 | 1.0 | 0.67 | 0.825 |
| Quante risme di carta A4 abbiamo comprato e a che prezzo? | F0001 | F0001, F0015, F0010, F0011 | 1.0 | 1.0 | 0.8 | 0.8 | 0.946 |
| Quali consulenze abbiamo ricevuto? | F0005, F0010, F0011 | F0005, F0010, F0011, F0012 | 0.0 | 1.0 | 1.0 | 0.33 | 0.772 |
| Chi si occupa delle pulizie degli uffici? | F0008 | F0008, F0010, F0011, F0012 | 1.0 | 1.0 | 1.0 | 0.86 | 0.876 |
| C'è una fattura in reverse charge? | F0008 | F0008, F0012, F0009, F0001 | 1.0 | 1.0 | 1.0 | 0.86 | 0.735 |
| Per quale servizio abbiamo pagato l'IVA al 10%? | F0009 | F0008, F0009, F0010, F0015 | 0.5 | 1.0 | 0.333 | 0.67 | 0.641 |
| Quanto abbiamo pagato per le licenze SaaS del quarto trimestre? | F0007 | F0007, F0003, F0010, F0008 | 1.0 | 1.0 | 1.0 | 0.44 | 0.991 |
| Quanto costava una licenza SaaS nel terzo trimestre? | F0003 | F0003, F0007, F0010, F0005 | 1.0 | 1.0 | 1.0 | 0.57 | 0.967 |
| Chi ha installato il quadro elettrico? | F0012 | F0012, F0006, F0010, F0011 | 1.0 | 1.0 | 1.0 | 0.44 | 0.886 |
| Quanto cavo FG16 è stato fatturato? | F0012 | F0007, F0003, F0012, F0004 | 0.333 | 1.0 | 1.0 | 0.55 | 0.817 |
| Chi ha curato la campagna social? | F0011 | F0011, F0010, F0012, F0005 | 1.0 | 1.0 | 1.0 | 0.4 | 0.92 |
| Quale fornitore ha sviluppato il sito web? | F0010 | F0010, F0011, F0003, F0007 | 1.0 | 1.0 | 1.0 | 0.57 | 0.844 |
| Quanto è costata l'energia di agosto? | F0006 | F0006, F0012, F0008, F0005 | 1.0 | 1.0 | 1.0 | 0.91 | 0.824 |
| Chi ha trasportato le merci a giugno? | F0002 | F0002, F0005, F0004, F0001 | 1.0 | 1.0 | 1.0 | 0.57 | 0.797 |
| Cosa abbiamo comprato da Ottica Visione? | F0016 | F0016, F0010, F0011, F0012 | 1.0 | 1.0 | 1.0 | 0.73 | 0.0 |
| Abbiamo comprato delle sedie da ufficio? | — | F0010, F0011, F0004, F0001 | 1.0 | 1.0 | 1.0 | 0.4 | 0.57 |
