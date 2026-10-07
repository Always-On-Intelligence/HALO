# egocentric-copilot run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| A->S | output | 12 | 12 | 0 | 0 | buffer_frames: 146.0 -> 260.0; final_quality: 80.0 -> 25.0; hcc_correct: 1.0 -> 1.0; label_fact_recall: 0.875 -> 0.0; memory_fact_recall: 0.0 -> 0.0; model_calls: 7.0 -> 7.0; replies: 5.0 -> 5.0 |
| S->M | output_hcc | 12 | 12 | 0 | 0 | buffer_frames: 146.0 -> 1.0; final_quality: 80.0 -> 80.0; hcc_correct: 1.0 -> 0.0; label_fact_recall: 0.875 -> 0.875; memory_fact_recall: 0.0 -> 0.0; model_calls: 7.0 -> 4.0; replies: 5.0 -> 5.0 |
| M->A | output_hcc | 12 | 9 | 0 | 3 | buffer_frames: 146.0 -> 146.0; final_quality: 80.0 -> 80.0; hcc_correct: 1.0 -> 0.25; label_fact_recall: 0.875 -> 0.875; memory_fact_recall: 0.0 -> 0.0; model_calls: 7.0 -> 7.0; replies: 5.0 -> 5.0 |
