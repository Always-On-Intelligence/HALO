# omi run-mode report

5 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 15 | 10 | 3 | 2 | backbone_calls: 11.9333 -> 10.8; chat_expected_hits: 0.9333 -> 0.3; duplicate_tasks_last_day: 0.4 -> 0.4; failed_conversations: 0.0 -> 0.0; memories_written: 10.4 -> 0.0; notifications: 0.2 -> 0.2; repeated_notifications: 0.0 -> 0.0; tasks_last_day: 1.8667 -> 1.8667 |
| M->A | output | 15 | 14 | 0 | 1 | backbone_calls: 11.9333 -> 10.6; chat_expected_hits: 0.9333 -> 0.0; duplicate_tasks_last_day: 0.4 -> 0.4; failed_conversations: 0.0 -> 0.0; memories_written: 10.4 -> 10.4; notifications: 0.2 -> 0.2; repeated_notifications: 0.0 -> 0.0; tasks_last_day: 1.8667 -> 1.8667 |
| A->M | output | 15 | 2 | 3 | 10 | backbone_calls: 11.9333 -> 12.1333; chat_expected_hits: 0.9333 -> 1.0; duplicate_tasks_last_day: 0.4 -> 0.0; failed_conversations: 0.0 -> 0.0; memories_written: 10.4 -> 10.4; notifications: 0.2 -> 0.2667; repeated_notifications: 0.0 -> 0.0; tasks_last_day: 1.8667 -> 2.2 |
| A->S | output_tasks | 15 | 3 | 0 | 12 | backbone_calls: 11.9333 -> 12.0; chat_expected_hits: 0.9333 -> 1.0; duplicate_tasks_last_day: 0.4 -> 0.6; failed_conversations: 0.0 -> 0.0; memories_written: 10.4 -> 10.4; notifications: 0.2 -> 0.2; repeated_notifications: 0.0 -> 0.0; tasks_last_day: 1.8667 -> 2.2 |
| M->S | output_capture | 15 | 15 | 0 | 0 | backbone_calls: 11.9333 -> 10.2667; chat_expected_hits: 0.9333 -> 0.9667; duplicate_tasks_last_day: 0.4 -> 0.4; failed_conversations: 0.0 -> 0.0; memories_written: 10.4 -> 4.0; notifications: 0.2 -> 0.0; repeated_notifications: 0.0 -> 0.0; tasks_last_day: 1.8667 -> 2.2 |
