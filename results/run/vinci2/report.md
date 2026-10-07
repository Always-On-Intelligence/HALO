# vinci2 run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 12 | 3 | 0 | 9 | activity_captions: 2.0 -> 0.0; kg_nodes: 47.1667 -> 0.0; reminders: 0.25 -> 0.5; searches: 0.6667 -> 0.25; stored_captions: 4.0 -> 0.0 |
| M->A | output | 12 | 3 | 0 | 9 | activity_captions: 2.0 -> 2.0; kg_nodes: 47.1667 -> 47.1667; reminders: 0.25 -> 0.5; searches: 0.6667 -> 0.25; stored_captions: 4.0 -> 4.0 |
| A->M | output | 12 | 1 | 0 | 11 | activity_captions: 2.0 -> 2.0; kg_nodes: 47.1667 -> 47.1667; reminders: 0.25 -> 0.3333; searches: 0.6667 -> 1.0; stored_captions: 4.0 -> 4.0 |
