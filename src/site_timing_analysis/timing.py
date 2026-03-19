from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Iterable

from .models import StateInterval, StateLabeledEvent


_SOURCE_PRIORITY = {"auditlog": 0, "sessions": 1, "timing_log": 2}
_UNASSIGNED_STATE_VALUES = {"", "NA", "<NA>"}
_TERMINAL_SENSITIVE_STATES = {
    "Patient recovery & transfer",
    "Post-treatment scans & Device removal",
}
_EARLY_SENSITIVE_STATES = {
    "Room ready",
    "TULSA QA",
    "Patient positioning & induction",
}
_LARGE_GAP_THRESHOLD_SEC = 7200.0
_NEGATIVE_START_WARN_THRESHOLD_SEC = 21600.0
_EARLY_STATE_LONG_GAP_EVENT_TYPES = {
    "FPumpRecord",
    "PSConnectionRecord",
    "UATestRecord",
    "Ready4Urology",
}
_EARLY_STATE_LONG_GAP_RULES = {
    "carry_forward_previous_state",
    "map_uatest_pre_positioning",
    "map_anesthesia_or_urology_ready",
}


def _sort_key(event: StateLabeledEvent) -> tuple[object, ...]:
    raw_first = 0 if not event.is_synthetic else 1
    row_rank = event.row_number if event.row_number is not None else 10**12
    source_rank = _SOURCE_PRIORITY.get(event.source, 99)
    return (
        event.timestamp,
        raw_first,
        row_rank,
        source_rank,
        event.event_type,
        event.source_detail,
    )


def _normalized_state(state: str | None) -> str:
    if state is None:
        return "<NA>"
    text = state.strip()
    if text == "":
        return "<NA>"
    return text


def _is_unassigned_state(state: str | None) -> bool:
    return _normalized_state(state) in _UNASSIGNED_STATE_VALUES


def _is_meaningful_state(state: str | None) -> bool:
    return not _is_unassigned_state(state)


def _is_terminal_sensitive_state(state: str | None) -> bool:
    return _normalized_state(state) in _TERMINAL_SENSITIVE_STATES


def _is_early_sensitive_state(state: str | None) -> bool:
    return _normalized_state(state) in _EARLY_SENSITIVE_STATES


def _is_session_synthetic_event(event: StateLabeledEvent) -> bool:
    return event.is_synthetic and event.source == "sessions"


def _first_index(events: list[StateLabeledEvent], event_type: str) -> int | None:
    for idx, event in enumerate(events):
        if event.event_type == event_type:
            return idx
    return None


def _all_indexes(events: list[StateLabeledEvent], event_type: str) -> list[int]:
    return [idx for idx, event in enumerate(events) if event.event_type == event_type]


def _choose_rebase_anchor(
    events: list[StateLabeledEvent],
) -> tuple[str, float, list[str]]:
    """
    Choose legacy-aligned rebase anchor.

    Priority mirrors legacy behavior:
    - InitialImaging when available before Alignment and setup conditions are met
    - LastUAHoming when InitialImaging is absent and UA homing exists pre-Alignment
    - Alignment fallback

    If Alignment is absent, explicit fallback warnings are emitted.
    """
    case_id = events[0].case_id
    warnings: list[str] = []

    base_ts = events[0].timestamp
    alignment_idx = _first_index(events, "AlignmentWorkflowRecord")
    init_imaging_idx = _first_index(events, "InitialImaging")
    ua_homes = _all_indexes(events, "PSHomingRecord")

    if alignment_idx is None:
        if init_imaging_idx is not None:
            anchor_sec = (events[init_imaging_idx].timestamp - base_ts).total_seconds()
            warnings.append(f"{case_id}:rebase_missing_alignment:fallback=InitialImaging")
            return "InitialImaging", anchor_sec, warnings
        if ua_homes:
            anchor_sec = (events[ua_homes[-1]].timestamp - base_ts).total_seconds()
            warnings.append(f"{case_id}:rebase_missing_alignment:fallback=LastUAHoming")
            return "LastUAHoming", anchor_sec, warnings
        warnings.append(f"{case_id}:rebase_anchor_missing:fallback=CaseStart")
        return "CaseStart", 0.0, warnings

    ps_tests = _all_indexes(events, "PSTestRecord")
    ua_tests = _all_indexes(events, "UATestRecord")
    setup_idx = _first_index(events, "SetupWorkflowRecord")

    ps_before_alignment = [idx for idx in ps_tests if idx < alignment_idx]
    ua_tests_before_alignment = [idx for idx in ua_tests if idx < alignment_idx]
    ua_homes_before_alignment = [idx for idx in ua_homes if idx < alignment_idx]

    last_ps_test = 0
    if ps_before_alignment:
        last_ps_test = max(ps_before_alignment)
    if ua_tests_before_alignment:
        last_ps_test = max(last_ps_test, max(ua_tests_before_alignment))
    if last_ps_test <= 1:
        if len(ua_homes) > 1:
            last_ps_test = ua_homes[0]
        elif setup_idx is not None:
            last_ps_test = setup_idx

    ua_after_last_ps = [idx for idx in ua_homes if idx > last_ps_test]

    if ua_after_last_ps:
        if init_imaging_idx is not None and init_imaging_idx < alignment_idx:
            anchor_sec = (events[init_imaging_idx].timestamp - base_ts).total_seconds()
            return "InitialImaging", anchor_sec, warnings
        if init_imaging_idx is None and ua_homes_before_alignment:
            anchor_sec = (events[ua_homes_before_alignment[-1]].timestamp - base_ts).total_seconds()
            return "LastUAHoming", anchor_sec, warnings
        warnings.append(f"{case_id}:rebase_anchor_fallback:Alignment")

    anchor_sec = (events[alignment_idx].timestamp - base_ts).total_seconds()
    return "Alignment", anchor_sec, warnings


def _infer_case_end_timestamp(
    events: list[StateLabeledEvent],
) -> tuple[int, list[str]]:
    """
    Infer case-end from the last valid event with a meaningful state.

    Returns the index of the inferred case-end event and case-level warnings
    describing whether inference was ambiguous.
    """
    case_id = events[0].case_id
    meaningful_indexes = [idx for idx, event in enumerate(events) if _is_meaningful_state(event.state)]
    warnings: list[str] = []

    if not meaningful_indexes:
        warnings.append(f"{case_id}:case_end_ambiguous:no_meaningful_state:fallback=last_event")
        warnings.append(
            f"{case_id}:case_end_inferred:strategy=fallback_last_event:row={events[-1].row_number}:"
            f"timestamp={events[-1].timestamp.isoformat()}"
        )
        return len(events) - 1, warnings

    case_end_idx = meaningful_indexes[-1]
    case_end_event = events[case_end_idx]
    warnings.append(
        f"{case_id}:case_end_inferred:strategy=last_meaningful_state:row={case_end_event.row_number}:"
        f"state={_normalized_state(case_end_event.state)}:timestamp={case_end_event.timestamp.isoformat()}"
    )

    trailing_events = len(events) - (case_end_idx + 1)
    if trailing_events > 0:
        warnings.append(
            f"{case_id}:case_end_ambiguous:trailing_events_after_case_end={trailing_events}:"
            f"case_end_row={case_end_event.row_number}"
        )

    return case_end_idx, warnings


def compute_state_intervals(
    state_labeled_events: Iterable[StateLabeledEvent],
) -> tuple[list[StateInterval], list[str]]:
    """
    Build per-row state intervals and rebased starts from state-labeled events.

    Durations are computed as row-to-next-row timestamp deltas.
    The final row duration defaults to 0 seconds.
    """
    original = list(state_labeled_events)
    if not original:
        return [], []

    case_ids = {event.case_id for event in original}
    if len(case_ids) != 1:
        raise ValueError("compute_state_intervals expects events for a single case.")

    case_id = original[0].case_id
    warnings: list[str] = []

    has_non_monotonic_input = any(
        original[idx].timestamp < original[idx - 1].timestamp for idx in range(1, len(original))
    )
    ordered = sorted(original, key=_sort_key)
    reordered = ordered != original

    if has_non_monotonic_input:
        warnings.append(f"{case_id}:interval_non_monotonic_input:reordered_for_computation")
    elif reordered:
        warnings.append(f"{case_id}:interval_input_reordered_by_tiebreak")

    rebase_anchor, anchor_offset_sec, anchor_warnings = _choose_rebase_anchor(ordered)
    warnings.extend(anchor_warnings)
    case_end_idx, case_end_warnings = _infer_case_end_timestamp(ordered)
    warnings.extend(case_end_warnings)
    case_end_timestamp = ordered[case_end_idx].timestamp
    first_timestamp = ordered[0].timestamp
    anchor_timestamp = first_timestamp + timedelta(seconds=anchor_offset_sec)
    intervals: list[StateInterval] = []

    for idx, event in enumerate(ordered):
        quality_flags: list[str] = []
        if has_non_monotonic_input:
            quality_flags.append("non_monotonic_input")
        if reordered:
            quality_flags.append("input_reordered")

        if idx < len(ordered) - 1:
            next_event = ordered[idx + 1]
            raw_duration_sec = (next_event.timestamp - event.timestamp).total_seconds()
            if raw_duration_sec < 0:
                warnings.append(
                    f"{case_id}:interval_negative_duration:row={event.row_number}:"
                    f"event_type={event.event_type}:duration_sec={raw_duration_sec}"
                )
                quality_flags.append("negative_duration")
                duration_sec = 0.0
            elif raw_duration_sec == 0:
                quality_flags.append("zero_duration_to_next")
                duration_sec = 0.0
            else:
                duration_sec = raw_duration_sec
                effective_end_timestamp = next_event.timestamp
                is_unassigned_state = _is_unassigned_state(event.state)
                is_terminal_state = _is_terminal_sensitive_state(event.state)
                is_early_state = _is_early_sensitive_state(event.state)
                is_session_synthetic = _is_session_synthetic_event(event)
                large_gap = raw_duration_sec > _LARGE_GAP_THRESHOLD_SEC
                goes_past_case_end = next_event.timestamp > case_end_timestamp
                sparse_carry_forward = (
                    event.state_assignment_rule in _EARLY_STATE_LONG_GAP_RULES
                    or event.event_type in _EARLY_STATE_LONG_GAP_EVENT_TYPES
                    or is_session_synthetic
                )

                if goes_past_case_end and (is_unassigned_state or is_terminal_state):
                    # Clamp to inferred case end for terminal/unassigned states so
                    # sparse trailing events do not dominate case tail durations.
                    effective_end_timestamp = max(event.timestamp, case_end_timestamp)
                    if is_terminal_state:
                        quality_flags.append("interval_terminal_state_clamped")
                    if is_unassigned_state:
                        quality_flags.append("interval_unassigned_state_truncated")

                if large_gap and is_session_synthetic:
                    # Session-derived synthetic timestamps are sparse markers, not
                    # evidence that the synthetic state should span multi-hour/day gaps.
                    cap_timestamp = event.timestamp + timedelta(seconds=_LARGE_GAP_THRESHOLD_SEC)
                    if case_end_timestamp > event.timestamp and case_end_timestamp < cap_timestamp:
                        cap_timestamp = case_end_timestamp
                    if cap_timestamp < effective_end_timestamp:
                        effective_end_timestamp = cap_timestamp
                        quality_flags.append("interval_session_synthetic_truncated")
                        quality_flags.append("interval_truncated_large_gap")

                if large_gap and is_early_state and sparse_carry_forward:
                    cap_timestamp = event.timestamp + timedelta(seconds=_LARGE_GAP_THRESHOLD_SEC)
                    if case_end_timestamp > event.timestamp and case_end_timestamp < cap_timestamp:
                        cap_timestamp = case_end_timestamp
                    if cap_timestamp < effective_end_timestamp:
                        effective_end_timestamp = cap_timestamp
                        quality_flags.append("interval_early_state_truncated")
                        quality_flags.append("interval_truncated_large_gap")

                if large_gap and (is_unassigned_state or is_terminal_state or goes_past_case_end):
                    cap_timestamp = event.timestamp
                    cap_with_threshold = event.timestamp + timedelta(seconds=_LARGE_GAP_THRESHOLD_SEC)
                    if cap_with_threshold > cap_timestamp:
                        cap_timestamp = cap_with_threshold
                    if case_end_timestamp > event.timestamp and case_end_timestamp < cap_timestamp:
                        cap_timestamp = case_end_timestamp
                    if cap_timestamp < effective_end_timestamp:
                        effective_end_timestamp = cap_timestamp
                    quality_flags.append("interval_truncated_large_gap")
                    if is_terminal_state:
                        quality_flags.append("interval_terminal_state_clamped")
                    if is_unassigned_state:
                        quality_flags.append("interval_unassigned_state_truncated")

                duration_sec = (effective_end_timestamp - event.timestamp).total_seconds()
                if duration_sec < 0:
                    warnings.append(
                        f"{case_id}:interval_negative_duration_after_hardening:row={event.row_number}:"
                        f"event_type={event.event_type}:duration_sec={duration_sec}"
                    )
                    quality_flags.append("negative_duration")
                    duration_sec = 0.0

                if duration_sec < raw_duration_sec:
                    state_label = _normalized_state(event.state)
                    warnings.append(
                        f"{case_id}:interval_hardened_truncation:row={event.row_number}:"
                        f"event_type={event.event_type}:state={state_label}:"
                        f"raw_duration_sec={raw_duration_sec}:duration_sec={duration_sec}"
                    )
                    if "interval_early_state_truncated" in quality_flags:
                        warnings.append(
                            f"{case_id}:interval_early_state_truncated:row={event.row_number}:"
                            f"event_type={event.event_type}:state={state_label}:"
                            f"raw_duration_sec={raw_duration_sec}:duration_sec={duration_sec}"
                        )
                    if "interval_session_synthetic_truncated" in quality_flags:
                        warnings.append(
                            f"{case_id}:interval_session_synthetic_truncated:row={event.row_number}:"
                            f"event_type={event.event_type}:state={state_label}:"
                            f"source_detail={event.source_detail}:raw_duration_sec={raw_duration_sec}:"
                            f"duration_sec={duration_sec}"
                        )
        else:
            duration_sec = 0.0

        absolute_start_sec = (event.timestamp - first_timestamp).total_seconds()
        start_sec = absolute_start_sec - anchor_offset_sec
        if start_sec < 0:
            quality_flags.append("negative_rebased_start")
            expected_pre_anchor = event.timestamp < anchor_timestamp
            if expected_pre_anchor:
                quality_flags.append("negative_rebased_start_expected_pre_anchor")
            if (not expected_pre_anchor) or (abs(start_sec) > _NEGATIVE_START_WARN_THRESHOLD_SEC):
                warnings.append(
                    f"{case_id}:interval_negative_rebased_start:row={event.row_number}:"
                    f"event_type={event.event_type}:start_sec={start_sec}:"
                    f"expected_pre_anchor={int(expected_pre_anchor)}"
                )

        quality_flags = list(dict.fromkeys(quality_flags))

        intervals.append(
            StateInterval(
                case_id=event.case_id,
                timestamp=event.timestamp,
                state=event.state,
                start_sec=float(start_sec),
                duration_sec=float(duration_sec),
                rebase_anchor=rebase_anchor,
                origin_event_type=event.event_type,
                source=event.source,
                is_synthetic=event.is_synthetic,
                source_detail=event.source_detail,
                row_number=event.row_number,
                state_assignment_rule=event.state_assignment_rule,
                cleanup_rule_applied=event.cleanup_rule_applied,
                quality_flags=quality_flags,
                segment_id=event.segment_id,
                event_kind=event.event_kind,
                drop_reason=event.drop_reason,
                insertion_rule=event.insertion_rule,
                raw_payload=deepcopy(event.raw_payload),
            )
        )

    return intervals, warnings
