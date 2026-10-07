# Vendored Ouroboros code

- Repository: https://github.com/razzant/ouroboros
- Commit: 4b37f96223b4b8248eea80c9be22cf923759cd5a (release 7.6.0, "Merge pull request #1534: release 7.6.0")
- License: MIT (`LICENSE`, copied unchanged)

Every file below is copied unchanged at its upstream path (verified byte-for-byte with `cmp`). The set is what
the run executes: the 341 Python modules are exactly those imported while the adapter ran every arm of all four
items and the review-block, parse-failure, no-op, declined-promotion, memory-action and plan_task branches with a
scripted model, plus the data files the run reads or the commit path rewrites. Nothing else from the 640-module
package is copied.

## Data files

| File | Role in the run |
|---|---|
| `prompts/SYSTEM.md` | the base prompt of every action context; the file the evolution cycle may revise (a sandbox copy per run) |
| `BIBLE.md` | the constitution: second block of every action context and the reviewers' constitutional head; protected |
| `docs/CHECKLISTS.md`, `docs/CHECKLISTS_ARCHIVE.md` | the Repo Commit Checklist and standing disclosures of the triad packet (`tools/review.py` `_load_checklist_section`) and the Plan Review Checklist |
| `docs/DESIGN.md` | the design-system rules that the triad packet inlines when a change touches `web/` (the P9 carriers under `web/` do) |
| `docs/DEVELOPMENT.md`, `docs/development/*.md` (14), `docs/architecture/*.md` (13) | the two reference books (entrypoints and chapters); read-only in the evolution sandbox and read on demand by the cycle; the composed Architecture book is the constitutional pack of plan review, and the Development chapters are the change-class governance of the triad packet |
| `VERSION`, `README.md`, `docs/ARCHITECTURE.md`, `pyproject.toml`, `uv.lock`, `web/package.json`, `web/package-lock.json`, `web/modules/api_types.js`, `site/install/index.html`, `docs/install/index.html` | the release carriers (BIBLE P9) that the evolution bumps and `tools/release_sync.py` syncs before the preflight and the triad review |

## Modules and the part of the loop they run

| Loop part | Main upstream entry points (all called from the adapter) |
|---|---|
| task intake, dialogue memory | `supervisor/message_bus.py` `log_chat`; `ouroboros/memory.py` `Memory`; `ouroboros/memory_view.py` `capture_memory_view`, `render_story`, `render_room` |
| action context (memory to action) | `ouroboros/context.py` `build_memory_sections`, `build_knowledge_sections`, `build_recent_sections`; `ouroboros/improvement_backlog.py` `format_backlog_digest` |
| tool schemas offered to the model | `ouroboros/tools/core.py`, `ouroboros/tools/shell.py`, `ouroboros/tools/git.py`, `ouroboros/tools/control.py` (`get_tools`) |
| round limit | `ouroboros/runtime_limits.py` `get_max_rounds` |
| post-task stages | `ouroboros/post_task_synthesis.py` `_run_memory_fallback_draft`, `_run_scratchpad_consolidation`, `_run_reflection`, `_apply_reflection_memory_actions`, `_update_improvement_backlog`, `build_trace_summary` |
| experience review and its memory | `ouroboros/reflection.py` (`should_generate_reflection`, `generate_reflection`, `append_reflection_routed`, Pattern Register), `ouroboros/consolidator.py`, `ouroboros/knowledge.py`, `ouroboros/improvement_backlog.py`, `ouroboros/semantic_dedup.py` |
| proposal (promotion) | `ouroboros/post_task_evolution.py` `maybe_promote`, `apply_pending_request` |
| campaign and cycle task | `supervisor/evolution_lifecycle.py` `start_evolution_campaign`, `enqueue_evolution_task_if_needed`, `begin_evolution_transaction`, `build_evolution_task_text`; `supervisor/state.py`, `supervisor/queue.py` |
| review gate | `ouroboros/tools/review.py` (`_preflight_check`, `_load_checklist_section`, `_triad_governance_context`, `_REVIEW_PROMPT_TEMPLATE_*`, `_dispatch_unified_review`, `_handle_review_block_or_warning`), `ouroboros/tools/review_helpers.py`, `ouroboros/tools/review_file_pack.py`, `ouroboros/tools/review_multi_model.py` `triad_api_messages`, `ouroboros/tools/review_response.py`, `ouroboros/triad_review.py`, `ouroboros/reviewer_slot_config.py`, `ouroboros/review_cycles.py` |
| release metadata | `ouroboros/tools/release_sync.py` `sync_release_metadata`; `ouroboros/commit_admission.py` `release_metadata_diagnostics` |
| plan review (`plan_task`) | `ouroboros/tools/plan_review.py` `_handle_plan_task` and its engine (`plan_review_runtime.py`, `plan_review_collect.py`, `plan_spec.py`, `plan_packet.py`, `plan_evidence.py`, `plan_render.py`, `plan_dialogue.py`, `plan_review_references.py`, `plan_review_artifacts.py`) |

The remaining modules are their import-time and call-time dependencies (config, settings, observability,
usage accounting, chronicle store, tool registry types, and so on).

## Not copied, or present only as an import dependency

Not copied: the tool loop (`ouroboros/loop*.py`, `ouroboros/agent.py`, `ouroboros/agent_task_pipeline.py`), the
web gateway and server (`ouroboros/gateway/settings.py` among them), the launcher, the Claudexor runtime, tests, the
web UI, skills and most tools. The adapter ports the loop (see ../README.md).

Present as import dependencies whose request paths are never reached: the model client `ouroboros/llm.py` and its
provider lanes (`llm_*.py`, `openai_chat_*.py`), which the adapter replaces by the HALO backbone through
`ouroboros.llm.LLMClient` before any upstream function runs, and the reviewer fan-out
(`tools/review_multi_model.py` `_handle_multi_model_review`, `tools/plan_review_runtime.py` `run_plan_review_slots`,
`review_substrate.py` `run_review_request`), which the adapter replaces by its reviewer transports. The git helpers on the run's path (`tools/review.py` `_git_show_staged`,
`tools/review_file_pack.py` `_git_blob_text`, `supervisor/git_ops.py` `git_capture`) are answered from the sandbox
copy, so no git process runs.

## Python modules (385 files in total with the 44 data files)

- `ouroboros/` (212): __init__, _outcome_receipts, _outcome_tool_errors, _usage_cache_splits, _usage_money, _usage_response, _usage_rows, _usage_rows_memo, acceptance_preparation, agent_dispatch, agent_startup_checks, anthropic_native_custody, artifacts, budget_pause, capability_evidence, chat_chain, chronicle_import, chronicle_store, claudexor_daemon, claudexor_startup_failure, code_search_rg, commit_admission, config, configured_subagents, consciousness_authority, consolidator, context, context_budget, context_compaction, context_fit, context_health, context_input_selection, context_layout, context_mode_compat, context_runtime_facts, cost_projection, credential_shapes, deadline_utils, delegate_custody, delegate_custody_reconcile, delegate_custody_usage, delegate_evidence, delegate_registration_policy, delegate_shared, delegate_source_coverage, deliverables_paths, depth_evidence, desktop_autostart, dialogue_evidence, dialogue_provenance, effort_evidence, event_bus, evolution_checkpoints, evolution_fingerprint, focus, git_shell_policy, headless, headless_status, i18n_memory, improvement_backlog, jsonl_tail, knowledge, launcher_bootstrap, llm, llm_anthropic, llm_attempt, llm_capability_policy, llm_claudexor, llm_fallback, llm_gigachat, llm_local, llm_messages, llm_observability, llm_openai_compatible, llm_pricing, llm_routing, llm_stream, llm_substitution, markdown_source, memory, memory_fallback, memory_inventory, memory_view, memory_view_legacy, model_slots, model_wait, net_transport, node_runtime, observability, openai_chat_custom, openai_chat_dispatch, openrouter_attribution, outcome_receipt_store, outcomes, owner_mailbox, owner_pause, owner_wait, owner_words, plan_review_facts, platform_layer, post_task_checkpoint, post_task_evolution, post_task_synthesis, presence_authority, presence_capabilities, presence_profile, presence_runtime, pricing, process_containment, process_custody, process_interpreters, project_admission, project_dialogue, project_facts, projects_registry, protected_artifacts, provider_models, reasoning_artifacts, reference_books, reflection, request_wire_attempt, request_wire_contract, request_wire_custom_validation, request_wire_receipts, request_wire_recovery, request_wire_resolution, retention, review_custody, review_cycles, review_dispatch, review_evidence, review_evidence_refs, review_evidence_sections, review_execution, review_execution_projection, review_model_routes, review_native_episode, review_operation, review_owner_custody, review_projection, review_records, review_session_custody, review_session_preparation, review_session_usage, review_slot_cancel, review_state, review_state_custody, review_state_model, review_state_records, review_status_projection, review_substrate, review_verdict, review_verdict_extraction, reviewer_slot_config, reviewer_window, route_spec, runtime_limits, runtime_mode_policy, schedule_contract, secret_masking, semantic_dedup, send_clock, settings_defaults, settings_integrity, settings_scales, shell_parse, skill_conflicts, skill_loader, skill_review_status, skill_review_usage, skill_token, subagent_dispatch_notes, subagent_history, subagent_messages, subagent_route_health, subagent_runtime, subagents, synthesis_cost_text, task_custody, task_finalization, task_pacing, task_result_facts, task_result_schema, task_results, task_status, terminal_projection, terminal_time, tool_access, tool_access_paths, tool_access_roots, tool_access_types, tool_access_user_files, tool_call_log, tool_capabilities, tool_policy, transport_custody, triad_review, ui_language, update_channels, update_letter, usage_accounting, usage_admission, usage_compaction, usage_ledger, usage_legacy_import, utils, version, windows_autostart, workspace_executor, workspace_file_outputs, workspace_patch_capture, workspace_patch_rules
- `ouroboros/contracts/` (10): __init__, chat_id_policy, plugin_api, schema_versions, skill_manifest, skill_payload_policy, task_constraint, task_contract, tool_abi, tool_context
- `ouroboros/gateway/` (1): __init__
- `ouroboros/gateways/` (2): __init__, claudexor
- `ouroboros/tools/` (72): __init__, arg_feedback, chronicle, claude_advisory_review, commit_gate, compact_context, control, control_delegation, control_events, control_routing, control_runtime, control_scheduling, control_subagent_spec, control_task_results, core, core_artifacts, core_file_tools, core_secret_paths, deliverables_shell, extension_dispatch, git, git_evolution, git_plumbing, git_repo_edit, git_review_cycle, git_vcs_ops, governance_context, knowledge, parallel_review, plan_dialogue, plan_evidence, plan_packet, plan_render, plan_review, plan_review_artifacts, plan_review_collect, plan_review_references, plan_review_runtime, plan_spec, preflight_review_prompt, preflight_review_run, process_facts, registry, registry_core, registry_guard_process, registry_guards, release_sync, review, review_admission, review_file_pack, review_helpers, review_multi_model, review_prompt_text, review_response, review_revalidation, review_synthesis, scope_required_sources, scope_review, scope_review_contract, scope_window, shell, shell_audit, shell_effects, shell_guards, shell_outputs, shell_process, tool_catalog, tool_context, tool_resolution, tool_result, verify, write_shape
- `supervisor/` (44): __init__, budget_resume, cancel_publication, cognitive_operations, direct_roots, events, events_budget, events_chat_delivery, events_coop_checkpoint, events_evolution_done, events_project_routing, events_runtime_controls, events_schedule_task, events_subagent_admission, events_task_done, events_worker_reports, evolution_lifecycle, git_ops, git_ops_remotes, git_ops_rescue, git_ops_reset, git_ops_updates, log_addressing, message_bus, queue, queue_schedules, queue_snapshot, queue_timeouts, queue_transitions, schedule_lifecycle, schedule_time, state, state_initialization, steering, task_admission, task_dispatch, task_lifecycle, task_model_wait, task_reaper, telemetry_events, update_recovery, update_source, worker_owner_wait, worker_pool_lifecycle
