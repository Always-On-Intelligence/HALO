# lightmem-ego run-mode report

5 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 15 | 14 | 1 | 0 | mlt_episodes: 1.0 -> 0.0; model_calls: 13.0 -> 2.0; mst_events: 5.0 -> 0.0; mst_refined: 5.0 -> 0.0; q1_fact_recall: 1.0 -> 0.0; q2_fact_recall: 0.6 -> 0.0; q2_followup_resolved: 1.0 -> 1.0 |
| M->A | output | 15 | 14 | 1 | 0 | mlt_episodes: 1.0 -> 1.0; model_calls: 13.0 -> 13.0; mst_events: 5.0 -> 5.0; mst_refined: 5.0 -> 5.0; q1_fact_recall: 1.0 -> 0.0; q2_fact_recall: 0.6 -> 0.0; q2_followup_resolved: 1.0 -> 0.0 |
| A->M | output_q2 | 15 | 3 | 3 | 9 | mlt_episodes: 1.0 -> 1.0; model_calls: 13.0 -> 13.0; mst_events: 5.0 -> 5.0; mst_refined: 5.0 -> 5.0; q1_fact_recall: 1.0 -> 1.0; q2_fact_recall: 0.6 -> 0.6; q2_followup_resolved: 1.0 -> 0.0 |
