# proact run-mode report

5 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 15 | 14 | 1 | 0 | backbone_calls: 36.1333 -> 34.6667; idle_facts_stored: 2.9333 -> 0.0; idle_intents: 0.8667 -> 0.9333; key_fact_recall: 0.5399 -> 0.4593; pushed: 0.1333 -> 0.0; reply_searched: 0.9333 -> 1.0 |
| M->A | output | 15 | 13 | 1 | 1 | backbone_calls: 36.1333 -> 22.8; idle_facts_stored: 2.9333 -> 0.0; idle_intents: 0.8667 -> 0.0; key_fact_recall: 0.5399 -> 0.4377; pushed: 0.1333 -> 0.0; reply_searched: 0.9333 -> 1.0 |
| A->S | output | 15 | 6 | 8 | 1 | backbone_calls: 36.1333 -> 35.9333; idle_facts_stored: 2.9333 -> 2.0667; idle_intents: 0.8667 -> 0.7333; key_fact_recall: 0.5399 -> 0.6376; pushed: 0.1333 -> 0.2667; reply_searched: 0.9333 -> 0.7333 |
| M->S | output | 15 | 8 | 5 | 2 | backbone_calls: 36.1333 -> 34.4667; idle_facts_stored: 2.9333 -> 2.2; idle_intents: 0.8667 -> 0.7333; key_fact_recall: 0.5399 -> 0.4924; pushed: 0.1333 -> 0.0667; reply_searched: 0.9333 -> 0.9333 |
| A->M | output | 15 | 9 | 5 | 1 | backbone_calls: 36.1333 -> 35.1333; idle_facts_stored: 2.9333 -> 2.3333; idle_intents: 0.8667 -> 0.8; key_fact_recall: 0.5399 -> 0.6882; pushed: 0.1333 -> 0.5333; reply_searched: 0.9333 -> 1.0 |
