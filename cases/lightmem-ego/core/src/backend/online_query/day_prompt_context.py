from __future__ import annotations

from typing import Any


def build_day_context_block(day_context: dict[str, Any] | None) -> str:
    if not isinstance(day_context, dict):
        return ""
    day_label = str(day_context.get("day_label") or "").strip()
    display_day_label = str(day_context.get("display_day_label") or "").strip()
    weekday_label = str(day_context.get("weekday_label") or "").strip()
    if not day_label and not display_day_label:
        return ""

    lines = ["Current Rokid day context:"]
    lines.append(f"- current_day: {display_day_label or day_label}")
    if day_context.get("day_index") is not None:
        lines.append(f"- current_day_index: {day_context['day_index']}")
    if day_label:
        lines.append(f"- current_day_label: {day_label}")
    if weekday_label:
        lines.append(f"- current_weekday: {weekday_label}")
    run_id = str(day_context.get("run_id") or "").strip()
    if run_id:
        lines.append(f"- current_run_id: {run_id}")
    if day_context.get("relative_ts_base_ms") is not None:
        lines.append(f"- current_day_relative_start_ms: {day_context['relative_ts_base_ms']}")
    lines.append("Use this day context as authoritative for relative-day and weekday references.")
    return "\n".join(lines)
