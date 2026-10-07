# pask run-mode report

5 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 15 | 15 | 0 | 0 | interventions: 3.2667 -> 2.0; memory_chars_delivered: 2196.4667 -> 0.0; need_turn_hit_rate: 1.0 -> 0.8; need_turn_uses_earlier_rate: 1.0 -> 0.1333; other_turn_interventions: 2.2667 -> 1.2 |
| M->A | output | 15 | 15 | 0 | 0 | interventions: 3.2667 -> 2.0; memory_chars_delivered: 2196.4667 -> 0.0; need_turn_hit_rate: 1.0 -> 0.8; need_turn_uses_earlier_rate: 1.0 -> 0.1333; other_turn_interventions: 2.2667 -> 1.2 |
