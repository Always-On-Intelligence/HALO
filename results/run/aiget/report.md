# aiget run-mode report

6 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| M->S | output | 18 | 5 | 10 | 3 | revisit_mean_max_similarity: 0.4267 -> 0.4621; revisit_repeats: 0.0 -> 0.0; shown: 1.7778 -> 1.7222; shown_revisit: 1.3333 -> 1.3889 |
| M->A | output | 18 | 6 | 6 | 6 | revisit_mean_max_similarity: 0.4267 -> 0.4591; revisit_repeats: 0.0 -> 0.0; shown: 1.7778 -> 1.8333; shown_revisit: 1.3333 -> 1.4444 |
| M->A+M->S | output | 18 | 13 | 4 | 1 | revisit_mean_max_similarity: 0.4267 -> 0.438; revisit_repeats: 0.0 -> 0.0; shown: 1.7778 -> 1.8333; shown_revisit: 1.3333 -> 1.5 |
| A->M | output_revisit | 18 | 15 | 0 | 3 | revisit_mean_max_similarity: 0.4267 -> 0.7459; revisit_repeats: 0.0 -> 1.0556; shown: 1.7778 -> 1.7778; shown_revisit: 1.3333 -> 1.6667 |
