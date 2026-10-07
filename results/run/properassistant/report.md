# properassistant run-mode report

2 items x 3 samples; backbone codex:gpt-6-astra (low); judge codex:gpt-6-astra (high)

| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |
|---|---|---|---|---|---|---|
| S->M | output | 6 | 1 | 2 | 3 | backbone_calls: 22.8333 -> 24.5; learn_mean_rating: 3.1111 -> 3.2778; learn_preference_pairs: 0.6667 -> 0.6667; pairs_in_policy: 0.6667 -> 0.6667; test_mean_rating: 3.3334 -> 3.3334; test_recommendations: 1.5 -> 1.5 |
| M->A | output | 6 | 3 | 2 | 1 | backbone_calls: 22.8333 -> 24.0; learn_mean_rating: 3.1111 -> 3.0556; learn_preference_pairs: 0.6667 -> 1.5; pairs_in_policy: 0.6667 -> 1.5; test_mean_rating: 3.3334 -> 3.4445; test_recommendations: 1.5 -> 2.1667 |
| A->M | output | 6 | 1 | 3 | 2 | backbone_calls: 22.8333 -> 25.5; learn_mean_rating: 3.1111 -> 3.2222; learn_preference_pairs: 0.6667 -> 1.1667; pairs_in_policy: 0.6667 -> 1.1667; test_mean_rating: 3.3334 -> 3.3889; test_recommendations: 1.5 -> 2.1667 |
| record | output | 6 | 1 | 2 | 3 | backbone_calls: 22.8333 -> 22.0; learn_mean_rating: 3.1111 -> 3.1111; learn_preference_pairs: 0.6667 -> 0.6667; pairs_in_policy: 0.6667 -> 0.0; test_mean_rating: 3.3334 -> 3.1667; test_recommendations: 1.5 -> 1.0 |
| outcome | output | 6 | 1 | 2 | 3 | backbone_calls: 22.8333 -> 22.0; learn_mean_rating: 3.1111 -> 3.1111; learn_preference_pairs: 0.6667 -> 0.6667; pairs_in_policy: 0.6667 -> 0.0; test_mean_rating: 3.3334 -> 3.1667; test_recommendations: 1.5 -> 1.0 |
| attribution | output | 6 | 3 | 0 | 3 | backbone_calls: 22.8333 -> 21.0; learn_mean_rating: 3.1111 -> 3.1111; learn_preference_pairs: 0.6667 -> 0.6667; pairs_in_policy: 0.6667 -> 0.6667; test_mean_rating: 3.3334 -> 3.0556; test_recommendations: 1.5 -> 0.6667 |
| revision | output | 6 | 1 | 2 | 3 | backbone_calls: 22.8333 -> 22.0; learn_mean_rating: 3.1111 -> 3.1111; learn_preference_pairs: 0.6667 -> 0.6667; pairs_in_policy: 0.6667 -> 0.0; test_mean_rating: 3.3334 -> 3.1667; test_recommendations: 1.5 -> 1.0 |
