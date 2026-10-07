# proactive-agent run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 12 | 5 | 2 | 5 | acceptance_rate: 1.0 -> 0.95; accepted: 1.0 -> 1.25; backbone_calls: 10.6667 -> 12.3333; executed_actions: 2.3333 -> 2.8333; failed_steps: 0.0 -> 0.0; label_agreement: 0.4792 -> 0.5208; observed_action_events: 17.75 -> 17.5; proposals: 1.0 -> 1.3333 |
| M->A | output | 12 | 5 | 2 | 5 | acceptance_rate: 1.0 -> 1.0; accepted: 1.0 -> 0.75; backbone_calls: 10.6667 -> 9.6667; executed_actions: 2.3333 -> 2.0833; failed_steps: 0.0 -> 0.0; label_agreement: 0.4792 -> 0.5; observed_action_events: 17.75 -> 17.1667; proposals: 1.0 -> 0.75 |
| A->S | output | 12 | 6 | 2 | 4 | acceptance_rate: 1.0 -> 0.7593; accepted: 1.0 -> 1.0; backbone_calls: 10.6667 -> 12.1667; executed_actions: 2.3333 -> 5.3333; failed_steps: 0.0 -> 0.0; label_agreement: 0.4792 -> 0.4583; observed_action_events: 17.75 -> 0.0; proposals: 1.0 -> 1.4167 |
