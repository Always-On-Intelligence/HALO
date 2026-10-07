# m3-agent run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 12 | 12 | 0 | 0 | characters: 3.4167 -> 6.5; control_rounds: 2.5417 -> 5.0; correct: 0.875 -> 0.0; empty_searches: 0.25 -> 8.0; identities_reused: 10.5 -> 10.5; text_memories: 62.25 -> 0.0 |
| M->A | output | 12 | 12 | 0 | 0 | characters: 3.4167 -> 3.4167; control_rounds: 2.5417 -> 5.0; correct: 0.875 -> 0.0; empty_searches: 0.25 -> 8.0; identities_reused: 10.5 -> 10.5; text_memories: 62.25 -> 62.25 |
| M->S | output | 12 | 6 | 1 | 5 | characters: 3.4167 -> 9.4167; control_rounds: 2.5417 -> 3.1667; correct: 0.875 -> 0.7917; empty_searches: 0.25 -> 1.5; identities_reused: 10.5 -> 0.0; text_memories: 62.25 -> 66.1667 |
