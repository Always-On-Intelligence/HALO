# pahf run-mode report

6 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 18 | 16 | 0 | 2 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 0.0; test1_correct: 0.8889 -> 0.0; test2_correct: 0.0 -> 0.3333; test_accuracy: 0.4444 -> 0.1667 |
| S->M | output_other | 18 | 0 | 6 | 12 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 0.0; test1_correct: 0.8889 -> 0.0; test2_correct: 0.0 -> 0.3333; test_accuracy: 0.4444 -> 0.1667 |
| M->A | output | 18 | 16 | 0 | 2 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 1.7222; test1_correct: 0.8889 -> 0.0; test2_correct: 0.0 -> 0.3333; test_accuracy: 0.4444 -> 0.1667 |
| M->A | output_other | 18 | 0 | 6 | 12 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 1.7222; test1_correct: 0.8889 -> 0.0; test2_correct: 0.0 -> 0.3333; test_accuracy: 0.4444 -> 0.1667 |
| A->S | output | 18 | 2 | 2 | 14 | backbone_calls: 19.1111 -> 17.4444; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.0; notes_after_learning: 1.7222 -> 0.9444; test1_correct: 0.8889 -> 0.8889; test2_correct: 0.0 -> 0.1111; test_accuracy: 0.4444 -> 0.5 |
| A->S | output_other | 18 | 0 | 2 | 16 | backbone_calls: 19.1111 -> 17.4444; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.0; notes_after_learning: 1.7222 -> 0.9444; test1_correct: 0.8889 -> 0.8889; test2_correct: 0.0 -> 0.1111; test_accuracy: 0.4444 -> 0.5 |
| A->M | output | 18 | 0 | 2 | 16 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 1.6111; test1_correct: 0.8889 -> 1.0; test2_correct: 0.0 -> 0.0; test_accuracy: 0.4444 -> 0.5 |
| A->M | output_other | 18 | 0 | 0 | 18 | backbone_calls: 19.1111 -> 19.1111; learn_asked: 0.7778 -> 0.7778; learn_correct: 0.7778 -> 0.7778; notes_after_learning: 1.7222 -> 1.6111; test1_correct: 0.8889 -> 1.0; test2_correct: 0.0 -> 0.0; test_accuracy: 0.4444 -> 0.5 |
