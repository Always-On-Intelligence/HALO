# visionclaw run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 12 | 9 | 0 | 3 | agent_calls: 2.5 -> 2.75; app_writes_attempted: 0.75 -> 0.75; app_writes_kept: 0.75 -> 0.0; delegated_turns: 1.0 -> 1.0833; final_facts_stated: 0.9375 -> 0.4444; frames_attached: 0.8333 -> 0.8333; ledger_entries: 1.0 -> 1.0833; notes_saved: 1.0 -> 0.0; parked_relayed: 0.25 -> 0.25; voice_model_calls: 7.25 -> 7.0833 |
| M->A | output | 12 | 12 | 0 | 0 | agent_calls: 2.5 -> 2.5833; app_writes_attempted: 0.75 -> 0.5; app_writes_kept: 0.75 -> 0.5; delegated_turns: 1.0 -> 1.0; final_facts_stated: 0.9375 -> 0.0; frames_attached: 0.8333 -> 0.8333; ledger_entries: 1.0 -> 1.0; notes_saved: 1.0 -> 1.25; parked_relayed: 0.25 -> 0.0; voice_model_calls: 7.25 -> 6.5 |
| A->M | output | 12 | 4 | 0 | 8 | agent_calls: 2.5 -> 2.5833; app_writes_attempted: 0.75 -> 0.75; app_writes_kept: 0.75 -> 0.75; delegated_turns: 1.0 -> 1.0; final_facts_stated: 0.9375 -> 0.6875; frames_attached: 0.8333 -> 0.8333; ledger_entries: 1.0 -> 0.0; notes_saved: 1.0 -> 1.0; parked_relayed: 0.25 -> 0.0; voice_model_calls: 7.25 -> 7.0 |
| A->S | output | 12 | 2 | 0 | 10 | agent_calls: 2.5 -> 2.5833; app_writes_attempted: 0.75 -> 0.75; app_writes_kept: 0.75 -> 0.75; delegated_turns: 1.0 -> 1.0; final_facts_stated: 0.9375 -> 0.9375; frames_attached: 0.8333 -> 0.0; ledger_entries: 1.0 -> 1.0; notes_saved: 1.0 -> 1.0; parked_relayed: 0.25 -> 0.25; voice_model_calls: 7.25 -> 7.3333 |
