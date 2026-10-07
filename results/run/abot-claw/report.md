# abot-claw run-mode report

4 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 12 | 2 | 0 | 10 | critic_calls: 0.5 -> 0.5; failed_requests: 1.5833 -> 1.5833; memory_queries: 3.0 -> 3.0833; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 7.4167; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 7.1667; task_success: 0.75 -> 0.75; turns: 10.5 -> 10.5 |
| M->A | output | 12 | 6 | 2 | 4 | critic_calls: 0.5 -> 0.25; failed_requests: 1.5833 -> 1.8333; memory_queries: 3.0 -> 4.0833; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 5.3333; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 4.5833; task_success: 0.75 -> 0.4167; turns: 10.5 -> 9.4167 |
| A->S | output | 12 | 0 | 4 | 8 | critic_calls: 0.5 -> 0.5833; failed_requests: 1.5833 -> 1.5833; memory_queries: 3.0 -> 3.0; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 6.75; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 6.5833; task_success: 0.75 -> 0.75; turns: 10.5 -> 10.5 |
| M->S | output | 12 | 0 | 2 | 10 | critic_calls: 0.5 -> 0.5833; failed_requests: 1.5833 -> 1.5833; memory_queries: 3.0 -> 3.0; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 7.0; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 6.4167; task_success: 0.75 -> 0.75; turns: 10.5 -> 10.5 |
| A->M | output | 12 | 0 | 0 | 12 | critic_calls: 0.5 -> 0.5; failed_requests: 1.5833 -> 1.5833; memory_queries: 3.0 -> 3.0; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 7.0; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 6.75; task_success: 0.75 -> 0.75; turns: 10.5 -> 10.5 |
| attribution | output | 12 | 0 | 2 | 10 | critic_calls: 0.5 -> 0.5; failed_requests: 1.5833 -> 1.5833; memory_queries: 3.0 -> 3.0; memory_writes: 1.3333 -> 1.3333; observations: 7.0 -> 7.1667; replied: 1.5 -> 1.5; robot_actions: 6.75 -> 6.5; task_success: 0.75 -> 0.75; turns: 10.5 -> 10.5833 |
