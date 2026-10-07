# user-as-code run-mode report

5 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 15 | 15 | 0 | 0 | answer_expected_hits: 0.9667 -> 0.0; facts_stored: 17.8 -> 0.0; modules_stored: 2.4 -> 2.4; pretrigger_alerts: 0.0 -> 0.0; trigger_alerts: 1.2 -> 0.0; trigger_rubric_passed: 1.0 -> 0.0; update_errors: 0.0 -> 0.0 |
| M->A | output_answer | 15 | 15 | 0 | 0 | answer_expected_hits: 0.9667 -> 0.0; facts_stored: 17.8 -> 17.8; modules_stored: 2.4 -> 2.4; pretrigger_alerts: 0.0 -> 0.0; trigger_alerts: 1.2 -> 1.2; trigger_rubric_passed: 1.0 -> 1.0; update_errors: 0.0 -> 0.0 |
| revision | output_alerts | 15 | 15 | 0 | 0 | answer_expected_hits: 0.9667 -> 0.9667; facts_stored: 17.8 -> 17.8; modules_stored: 2.4 -> 0.0; pretrigger_alerts: 0.0 -> 0.0; trigger_alerts: 1.2 -> 0.0; trigger_rubric_passed: 1.0 -> 0.0; update_errors: 0.0 -> 0.0 |
