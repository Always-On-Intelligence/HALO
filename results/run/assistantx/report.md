# assistantx run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| M->S | output | 12 | 8 | 1 | 3 | messages_sent: 3.0833 -> 3.4167; moves: 2.25 -> 1.6667; qr_codes_sent: 2.25 -> 1.6667; qr_codes_unused: 0.0 -> 0.0; steps: 3.9167 -> 4.4167; stopped: 0.8333 -> 0.5833; task_success: 1.0 -> 0.5833; undelivered: 0.0 -> 0.0 |
| M->A | output | 12 | 5 | 0 | 7 | messages_sent: 3.0833 -> 3.5833; moves: 2.25 -> 2.1667; qr_codes_sent: 2.25 -> 2.1667; qr_codes_unused: 0.0 -> 0.0; steps: 3.9167 -> 4.3333; stopped: 0.8333 -> 0.75; task_success: 1.0 -> 0.9167; undelivered: 0.0 -> 0.0 |
| M->A+M->S | output | 12 | 11 | 1 | 0 | messages_sent: 3.0833 -> 3.4167; moves: 2.25 -> 1.8333; qr_codes_sent: 2.25 -> 1.8333; qr_codes_unused: 0.0 -> 0.0; steps: 3.9167 -> 4.75; stopped: 0.8333 -> 0.6667; task_success: 1.0 -> 0.6667; undelivered: 0.0 -> 0.3333 |
| A->S | output | 12 | 9 | 0 | 3 | messages_sent: 3.0833 -> 3.75; moves: 2.25 -> 2.0833; qr_codes_sent: 2.25 -> 2.0833; qr_codes_unused: 0.0 -> 0.0; steps: 3.9167 -> 4.5; stopped: 0.8333 -> 0.75; task_success: 1.0 -> 0.8333; undelivered: 0.0 -> 0.0 |
