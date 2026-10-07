from __future__ import annotations

from typing import Any


__all__ = [
    "align_transcript_to_segments",
    "extract_audio_wav",
    "probe_video",
    "sample_keyframes_for_segments",
    "segment_video_into_clips",
    "transcribe_audio_with_whisperx",
    "transcribe_audio_with_xfyun",
    "synthesize_text_to_file",
    "attach_answer_audio_to_result",
    "write_empty_transcript_outputs",
    "write_em2mem_session_files",
]


def __getattr__(name: str) -> Any:
    if name in {"transcribe_audio_with_whisperx", "write_empty_transcript_outputs"}:
        from .asr_whisperx import transcribe_audio_with_whisperx, write_empty_transcript_outputs

        return {
            "transcribe_audio_with_whisperx": transcribe_audio_with_whisperx,
            "write_empty_transcript_outputs": write_empty_transcript_outputs,
        }[name]
    if name == "transcribe_audio_with_xfyun":
        from .asr_xfyun import transcribe_audio_with_xfyun

        return transcribe_audio_with_xfyun
    if name in {"synthesize_text_to_file", "attach_answer_audio_to_result"}:
        from .tts_xfyun import attach_answer_audio_to_result, synthesize_text_to_file

        return {
            "synthesize_text_to_file": synthesize_text_to_file,
            "attach_answer_audio_to_result": attach_answer_audio_to_result,
        }[name]
    if name == "extract_audio_wav":
        from .extract_audio import extract_audio_wav

        return extract_audio_wav
    if name == "sample_keyframes_for_segments":
        from .sample_keyframes import sample_keyframes_for_segments

        return sample_keyframes_for_segments
    if name in {"align_transcript_to_segments", "segment_video_into_clips"}:
        from .segment_video import align_transcript_to_segments, segment_video_into_clips

        return {
            "align_transcript_to_segments": align_transcript_to_segments,
            "segment_video_into_clips": segment_video_into_clips,
        }[name]
    if name == "probe_video":
        from .video_probe import probe_video

        return probe_video
    if name == "write_em2mem_session_files":
        from .em2mem_adapter import write_em2mem_session_files

        return write_em2mem_session_files
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
