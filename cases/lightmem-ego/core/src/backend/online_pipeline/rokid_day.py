from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from online_preprocess.io_utils import read_json, utc_now_iso, write_json_atomic

from .file_lock import FileLock


DAY_STATE_RELATIVE_PATH = Path("stream") / "day_state.json"
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WEEKDAY_LABELS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
TIME_CONTEXT_KEYS = (
    "start_datetime",
    "display_date",
    "display_time",
    "display_datetime",
    "display_iso",
    "display_hhmmssff",
    "timezone",
    "time_source",
    "client_session_start_ts_ms",
    "client_timezone_offset_minutes",
)


def _format_cn_date(value: datetime) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M:%S")


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _seconds_to_hhmmssff(seconds: float, fps_for_code: int = 100) -> str:
    total_frames = max(0, int(round(float(seconds or 0.0) * fps_for_code)))
    total_seconds, frames = divmod(total_frames, fps_for_code)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{secs:02d}{frames:02d}"


def _parse_iso_datetime(value: Any, tz: timezone | ZoneInfo) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed.astimezone(tz)
        except Exception:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except Exception:
            continue
    return None


def _timezone_from_metadata(metadata: dict[str, Any]) -> tuple[timezone | ZoneInfo, str]:
    tz_id = str(metadata.get("client_timezone_id") or metadata.get("timezone") or "").strip()
    if tz_id:
        try:
            return ZoneInfo(tz_id), tz_id
        except ZoneInfoNotFoundError:
            pass
    try:
        offset = int(metadata.get("client_timezone_offset_minutes"))
        return timezone(timedelta(minutes=offset)), f"UTC{offset / 60:+g}"
    except Exception:
        return timezone.utc, "UTC"


def _safe_epoch_ms(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def build_rokid_time_context(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(metadata or {})
    tz, tz_label = _timezone_from_metadata(payload)
    epoch_ms = _safe_epoch_ms(payload.get("client_session_start_ts_ms") or payload.get("client_start_ts_ms"))
    time_source = "client_device"
    if epoch_ms is not None:
        start = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone(tz)
    else:
        start = _parse_iso_datetime(payload.get("client_start_datetime") or payload.get("start_datetime"), tz)
        if start is None:
            start = _parse_iso_datetime(utc_now_iso(), timezone.utc) or datetime.now(timezone.utc)
            tz = timezone.utc
            tz_label = "UTC"
            time_source = "server_receive_fallback"
    return {
        "start_datetime": _format_datetime(start),
        "display_date": _format_cn_date(start),
        "display_time": _format_time(start),
        "display_datetime": _format_datetime(start),
        "display_iso": start.isoformat(timespec="seconds"),
        "display_hhmmssff": _seconds_to_hhmmssff(
            start.hour * 3600 + start.minute * 60 + start.second + start.microsecond / 1_000_000
        ),
        "timezone": tz_label,
        "time_source": time_source,
        "client_session_start_ts_ms": epoch_ms,
        "client_timezone_offset_minutes": payload.get("client_timezone_offset_minutes"),
    }


def _parse_context_start(value: dict[str, Any]) -> datetime | None:
    tz, _ = _timezone_from_metadata(value)
    return _parse_iso_datetime(value.get("display_iso") or value.get("start_datetime") or value.get("display_datetime"), tz)


def rokid_display_payload_for_relative_time(context: dict[str, Any] | None, relative_seconds: float) -> dict[str, Any]:
    payload = dict(context or {})
    start = _parse_context_start(payload)
    if start is None:
        fallback = build_rokid_time_context(payload)
        start = _parse_context_start(fallback) or datetime.now(timezone.utc)
        payload = {**fallback, **payload}
    value = start + timedelta(seconds=max(0.0, float(relative_seconds or 0.0)))
    return {
        "display_date": _format_cn_date(value),
        "display_time": _format_time(value),
        "display_datetime": _format_datetime(value),
        "display_iso": value.isoformat(timespec="seconds"),
        "display_hhmmssff": _seconds_to_hhmmssff(
            value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000
        ),
        "timezone": payload.get("timezone") or "UTC",
        "time_source": payload.get("time_source") or "unknown",
    }


def valid_session_id(session_id: str) -> bool:
    return bool(session_id) and all(ch.isalnum() or ch in {"-", "_"} for ch in session_id)


def normalize_run_id(run_id: Any) -> str:
    text = str(run_id or "").strip()
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", text)[:128]


def normalize_day_label(day_index: Any) -> str:
    return f"DAY{max(1, _safe_int(day_index, 1))}"


def weekday_label_for_day(day_index: Any) -> str:
    index = max(1, _safe_int(day_index, 1))
    return WEEKDAY_LABELS[(index - 1) % len(WEEKDAY_LABELS)]


def weekday_label_en_for_day(day_index: Any) -> str:
    index = max(1, _safe_int(day_index, 1))
    return WEEKDAY_LABELS_EN[(index - 1) % len(WEEKDAY_LABELS_EN)]


def display_day_label_for_day(day_index: Any) -> str:
    index = max(1, _safe_int(day_index, 1))
    return f"{normalize_day_label(index)} {weekday_label_for_day(index)}"


def day_state_path(session_dir: Path) -> Path:
    return Path(session_dir) / DAY_STATE_RELATIVE_PATH


def _empty_single_session_day_state(session_id: str) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "mode": "single_session",
        "session_id": session_id,
        "next_day_index": 1,
        "runs": {},
        "created_at": now,
        "updated_at": now,
    }


def load_single_session_day_state(session_dir: Path, session_id: str | None = None) -> dict[str, Any]:
    session_id = str(session_id or Path(session_dir).name)
    state = read_json(day_state_path(session_dir), default={})
    if not isinstance(state, dict) or state.get("mode") != "single_session":
        return _empty_single_session_day_state(session_id)
    state.setdefault("session_id", session_id)
    state.setdefault("next_day_index", 1)
    if not isinstance(state.get("runs"), dict):
        state["runs"] = {}
    return state


def save_single_session_day_state(session_dir: Path, state: dict[str, Any]) -> None:
    state["mode"] = "single_session"
    state["updated_at"] = utc_now_iso()
    write_json_atomic(day_state_path(session_dir), state)


def current_single_session_day_run(session_dir: Path) -> dict[str, Any] | None:
    state = load_single_session_day_state(session_dir)
    runs = [run for run in state.get("runs", {}).values() if isinstance(run, dict)]
    if not runs:
        return None
    runs.sort(key=lambda item: (_safe_int(item.get("day_index"), 0), str(item.get("created_at") or "")))
    return copy.deepcopy(runs[-1])


def _latest_index(session_dir: Path, state_file: str, key: str) -> int:
    state = read_json(session_dir / "stream" / state_file, default={})
    return _safe_int(state.get(key), -1) if isinstance(state, dict) else -1


def _latest_relative_ts_ms(session_dir: Path) -> int:
    values: list[int] = []
    for rel_path, keys in (
        (Path("stream") / "frame_state.json", ("latest_relative_ts_ms", "latest_memory_relative_ts_ms")),
        (Path("stream") / "audio_state.json", ("latest_relative_ts_ms",)),
        (Path("stream") / "rokid_state.json", ("latest_frame_relative_ts_ms", "latest_audio_relative_ts_ms")),
    ):
        state = read_json(session_dir / rel_path, default={})
        if not isinstance(state, dict):
            continue
        for key in keys:
            if state.get(key) is not None:
                values.append(max(0, _safe_int(state.get(key), 0)))
    return max(values) if values else -1


def next_single_session_upload_offsets(session_dir: Path) -> dict[str, int]:
    latest_relative_ts_ms = _latest_relative_ts_ms(session_dir)
    return {
        "next_frame_index": _latest_index(session_dir, "frame_state.json", "latest_frame_index") + 1,
        "next_audio_index": _latest_index(session_dir, "audio_state.json", "latest_audio_index") + 1,
        "relative_ts_base_ms": latest_relative_ts_ms + 1,
    }


def day_context_for_single_session_run(run: dict[str, Any]) -> dict[str, Any]:
    day_index = max(1, _safe_int(run.get("day_index"), 1))
    context = {
        "enabled": True,
        "mode": "single_session",
        "day_label": str(run.get("day_label") or normalize_day_label(day_index)),
        "day_index": day_index,
        "weekday_label": str(run.get("weekday_label") or weekday_label_for_day(day_index)),
        "weekday_label_en": str(run.get("weekday_label_en") or weekday_label_en_for_day(day_index)),
        "display_day_label": str(run.get("display_day_label") or display_day_label_for_day(day_index)),
        "run_id": str(run.get("run_id") or ""),
        "relative_ts_base_ms": max(0, _safe_int(run.get("start_relative_ts_ms"), 0)),
    }
    context.update({key: run.get(key) for key in TIME_CONTEXT_KEYS if run.get(key) is not None})
    return context


def reserve_single_session_day_run(
    *,
    session_dir: Path,
    session_id: str,
    run_id: str,
    input_mode: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not valid_session_id(session_id):
        raise ValueError("invalid session_id")
    normalized_run_id = normalize_run_id(run_id)
    if not normalized_run_id:
        raise ValueError("run_id is required")

    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    stream_dir = session_dir / "stream"
    stream_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(stream_dir / "day_state.lock"), timeout=30):
        state = load_single_session_day_state(session_dir, session_id)
        runs = state.setdefault("runs", {})
        existing = runs.get(normalized_run_id)
        if isinstance(existing, dict):
            return copy.deepcopy(existing), state

        day_index = max(1, _safe_int(state.get("next_day_index"), 1))
        now = utc_now_iso()
        offsets = next_single_session_upload_offsets(session_dir)
        run = {
            "run_id": normalized_run_id,
            "session_id": session_id,
            "day_index": day_index,
            "day_label": normalize_day_label(day_index),
            "weekday_label": weekday_label_for_day(day_index),
            "weekday_label_en": weekday_label_en_for_day(day_index),
            "display_day_label": display_day_label_for_day(day_index),
            "status": "started",
            "input_mode": input_mode,
            "start_relative_ts_ms": offsets["relative_ts_base_ms"],
            "next_frame_index": offsets["next_frame_index"],
            "next_audio_index": offsets["next_audio_index"],
            "created_at": now,
            "updated_at": now,
            **build_rokid_time_context(metadata),
        }
        if metadata:
            for key in ("source", "device_type", "device_id", "owner_id"):
                if metadata.get(key) is not None:
                    run[key] = metadata[key]
        runs[normalized_run_id] = run
        state["next_day_index"] = day_index + 1
        save_single_session_day_state(session_dir, state)
        return copy.deepcopy(run), state


def enrich_start_response_for_single_session_day(response: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    content = copy.deepcopy(response)
    content.update(
        {
            "session_id": str(run.get("session_id") or content.get("session_id") or ""),
            "day_context": day_context_for_single_session_run(run),
            "next_frame_index": max(0, _safe_int(run.get("next_frame_index"), 0)),
            "next_audio_index": max(0, _safe_int(run.get("next_audio_index"), 0)),
            "relative_ts_base_ms": max(0, _safe_int(run.get("start_relative_ts_ms"), 0)),
            "rokid_session_mode": "single_session",
        }
    )
    return content


def single_session_metadata_patch(run: dict[str, Any]) -> dict[str, Any]:
    context = day_context_for_single_session_run(run)
    return {
        "rokid_session_mode": "single_session",
        "day_context": context,
        "day_label": context["day_label"],
        "day_index": context["day_index"],
        "weekday_label": context["weekday_label"],
        "weekday_label_en": context["weekday_label_en"],
        "display_day_label": context["display_day_label"],
        "run_id": context["run_id"],
        "relative_ts_base_ms": context["relative_ts_base_ms"],
    }


def update_single_session_metadata(session_dir: Path, run: dict[str, Any]) -> None:
    path = Path(session_dir) / "metadata.json"
    payload = read_json(path, default={})
    if not isinstance(payload, dict):
        payload = {"session_id": Path(session_dir).name}
    patch = single_session_metadata_patch(run)
    payload.update(patch)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata.update(patch)
    payload["metadata"] = metadata
    write_json_atomic(path, payload)


def load_single_session_day_context(session_dir: Path) -> dict[str, Any] | None:
    run = current_single_session_day_run(session_dir)
    if run:
        return day_context_for_single_session_run(run)
    payload = read_json(Path(session_dir) / "metadata.json", default={})
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    context = {**metadata, **payload}.get("day_context")
    if isinstance(context, dict) and context.get("mode") == "single_session":
        return dict(context)
    return None


def day_context_for_relative_time(session_dir: Path, relative_seconds: float) -> dict[str, Any] | None:
    state = load_single_session_day_state(session_dir)
    runs = [run for run in state.get("runs", {}).values() if isinstance(run, dict)]
    if not runs:
        return load_single_session_day_context(session_dir)
    relative_ms = max(0, int(round(float(relative_seconds or 0.0) * 1000.0)))
    runs.sort(key=lambda item: _safe_int(item.get("start_relative_ts_ms"), 0))
    selected = runs[0]
    for run in runs:
        if relative_ms < _safe_int(run.get("start_relative_ts_ms"), 0):
            break
        selected = run
    return day_context_for_single_session_run(selected)


def apply_demo_day_fields(
    item: dict[str, Any],
    *,
    session_dir: Path,
    start_seconds: Any,
    end_seconds: Any | None = None,
) -> dict[str, Any]:
    context = day_context_for_relative_time(session_dir, _safe_float(start_seconds, 0.0))
    if not context:
        return item
    item.update(
        {
            "date": context["day_label"],
            "day_label": context["day_label"],
            "weekday_label": context["weekday_label"],
            "weekday_label_en": context["weekday_label_en"],
            "display_day_label": context["display_day_label"],
            "relative_day_start_ms": context["relative_ts_base_ms"],
        }
    )
    base_seconds = context["relative_ts_base_ms"] / 1000.0
    local_start = max(0.0, _safe_float(start_seconds, 0.0) - base_seconds)
    local_end = max(local_start, _safe_float(end_seconds if end_seconds is not None else start_seconds, local_start) - base_seconds)
    item["local_start_time"] = round(local_start, 3)
    item["local_end_time"] = round(local_end, 3)
    return item


def query_memory_ready(session_dir: Path) -> bool:
    config = read_json(Path(session_dir) / "em2mem" / "memory_config.json", default={})
    if not isinstance(config, dict):
        return False
    return bool(
        config.get("latest_ready_memory_version")
        or config.get("latest_fast_ready_version")
        or config.get("memory_version")
        or config.get("long_term_partial_ready")
        or str(config.get("status") or "") == "memory_ready"
    )


def resolve_query_long_term_candidates(
    session_id: str,
    sessions_root: Path,
    *,
    question: str = "",
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del question
    context = dict(query_context or resolve_query_session_context(session_id, sessions_root))
    selected_session_id = str(context.get("long_term_session_id") or session_id)
    session_dir = Path(sessions_root) / selected_session_id
    candidate = {
        "session_id": selected_session_id,
        "role": "session",
        "ready": query_memory_ready(session_dir),
        "memory_config_exists": (session_dir / "em2mem" / "memory_config.json").exists(),
        "reason": "single-session long-term memory",
    }
    return {
        "preferred_session_id": selected_session_id,
        "selected_session_id": selected_session_id,
        "selected_role": "session",
        "selected_reason": candidate["reason"],
        "candidates": [candidate],
    }


def resolve_query_session_context(session_id: str, sessions_root: Path) -> dict[str, Any]:
    context = load_single_session_day_context(Path(sessions_root) / session_id)
    result: dict[str, Any] = {
        "session_id": session_id,
        "realtime_session_id": session_id,
        "short_term_session_id": session_id,
        "long_term_session_id": session_id,
        "interaction_cache_session_id": session_id,
        "is_rokid_demo_day": bool(context),
        "day_context": context,
    }
    if context:
        result.update(context)
    else:
        result.update(
            {
                "day_label": None,
                "day_index": None,
                "weekday_label": None,
                "weekday_label_en": None,
                "display_day_label": None,
                "run_id": "",
                "relative_ts_base_ms": None,
            }
        )
    return result
