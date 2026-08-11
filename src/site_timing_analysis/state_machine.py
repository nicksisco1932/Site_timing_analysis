# Project: Site Timing Analysis
# File: src/site_timing_analysis/state_machine.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Assigns canonical operational states to enriched timing events.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Iterable

from .models import EnrichedEvent, StateLabeledEvent


_SOURCE_PRIORITY = {"auditlog": 0, "sessions": 1, "timing_log": 2}
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DIRECT_STATE_MAP: dict[str, tuple[str, str]] = {
    "SetupWorkflowRecord": ("TULSA QA", "map_setup_workflow"),
    "SetupUnlockWorkflowRecord": ("Room ready", "map_setup_unlock_workflow"),
    "AnesthesiaStart": ("Patient positioning & induction", "map_anesthesia_or_urology_ready"),
    "Ready4Urology": ("Patient positioning & induction", "map_anesthesia_or_urology_ready"),
    "DeviceInsertionBegins": ("Device insertion", "map_device_insertion"),
    "DeviceInsertionEnds": ("Device insertion", "map_device_insertion"),
    "InitialImaging": ("Device repositioning", "map_initial_imaging"),
    "AlignmentWorkflowRecord": ("Alignment", "map_alignment"),
    "CoarseWorkflowRecord": ("Coarse", "map_coarse"),
    "CoarseUnlockWorkflowRecord": ("Coarse", "map_coarse"),
    "DetailedWorkflowRecord": ("Detailed", "map_detailed"),
    "PlanReadyWorkflowRecord": ("Planning start angle", "map_plan_ready"),
    "PlanReadyCompleteWorkflowRecord": ("Planning start angle", "map_plan_ready"),
    "DeliveryInitializingWorkflowRecord": ("Initialization", "map_initialization"),
    "PlanReadyUserStoppedInitializationWorkflowRecord": ("Planning start angle", "map_plan_ready_stop_init"),
    "DeliveryInterruptedWorkflowRecord": ("Review", "map_delivery_interrupted_review"),
    "DeliveryWorkflowRecord": ("Treating", "map_delivery_treating"),
    "DeliveryResumedWorkflowRecord": ("Treating", "map_delivery_treating"),
    "ReviewWorkflowRecord": ("Post-treatment scans & Device removal", "map_review_post_treatment"),
    "DevicesRemovalStarts": ("Post-treatment scans & Device removal", "map_devices_removal"),
    "DevicesRemovalEnds": ("Post-treatment scans & Device removal", "map_devices_removal"),
    "PatientTransferBegins": ("Patient recovery & transfer", "map_patient_transfer"),
    "PatientTransferEnds": ("Patient recovery & transfer", "map_patient_transfer"),
}


def _sort_key(event: EnrichedEvent) -> tuple[object, ...]:
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


def _is_critical_unmapped_event(event_type: str) -> bool:
    if "WorkflowRecord" in event_type:
        return True
    if "Delivery" in event_type:
        return True
    if event_type in {
        "AnesthesiaStart",
        "Ready4Urology",
        "DeviceInsertionBegins",
        "DeviceInsertionEnds",
        "InitialImaging",
        "PatientTransferBegins",
        "PatientTransferEnds",
    }:
        return True
    return False


def _segment_prefix_date(segment_id: str | None) -> str | None:
    if segment_id is None:
        return None
    text = segment_id.strip()
    if len(text) < 10:
        return None
    prefix = text[:10]
    if _DATE_PREFIX_RE.match(prefix) is None:
        return None
    return prefix


def _resolve_state_transition(
    event: EnrichedEvent,
    *,
    has_seen_positioning_state: bool,
) -> tuple[str | None, str | None]:
    if event.event_type == "UATestRecord" and not has_seen_positioning_state:
        return "Room ready", "map_uatest_pre_positioning"

    if "DeliveryPaused" in event.event_type:
        return "Paused", "map_delivery_paused"

    mapped = _DIRECT_STATE_MAP.get(event.event_type)
    if mapped is not None:
        return mapped

    return None, None


def assign_states(enriched_events: Iterable[EnrichedEvent]) -> tuple[list[StateLabeledEvent], list[str]]:
    ordered = sorted(list(enriched_events), key=_sort_key)
    warnings: list[str] = []
    warned_unmapped_types: set[str] = set()
    out: list[StateLabeledEvent] = []

    curr_state: str | None = None
    seen_positioning_state = False

    for idx, event in enumerate(ordered):
        previous = ordered[idx - 1] if idx > 0 else None
        transition_state, transition_rule = _resolve_state_transition(
            event,
            has_seen_positioning_state=seen_positioning_state,
        )

        if transition_state is not None:
            curr_state = transition_state
            state_assignment_rule = transition_rule
        elif curr_state is not None:
            state_assignment_rule = "carry_forward_previous_state"
        else:
            state_assignment_rule = None
            if _is_critical_unmapped_event(event.event_type) and event.event_type not in warned_unmapped_types:
                warnings.append(f"{event.case_id}:state_unmapped_event_type:{event.event_type}")
                warned_unmapped_types.add(event.event_type)

        state = curr_state
        cleanup_rules_applied: list[str] = []

        if (
            previous is not None
            and event.event_type == "AlignmentWorkflowRecord"
            and previous.event_type == "CoarseWorkflowRecord"
            and event.timestamp == previous.timestamp
        ):
            state = None
            curr_state = None
            cleanup_rules_applied.append("clear_alignment_duplicate_coarse_same_timestamp")
            warnings.append(f"{event.case_id}:cleanup_alignment_duplicate:row={event.row_number}")

        if state == "Post-treatment scans & Device removal" and (
            event.event_type == "MriConnectionRecord"
            or (event.event_type == "SessionEventRecord" and event.event_kind == 1)
            or (event.event_type == "SegmentEventRecord" and event.event_kind == 2)
        ):
            state = None
            curr_state = None
            cleanup_rules_applied.append("clear_post_treatment_disconnect_events")
            warnings.append(f"{event.case_id}:cleanup_post_treatment_disconnect:row={event.row_number}")

        segment_date_prefix = _segment_prefix_date(event.segment_id)
        if state is not None and segment_date_prefix is not None:
            timestamp_date = event.timestamp.strftime("%Y-%m-%d")
            if segment_date_prefix != timestamp_date:
                state = None
                curr_state = None
                cleanup_rules_applied.append("clear_segment_date_mismatch")
                warnings.append(
                    f"{event.case_id}:cleanup_segment_date_mismatch:row={event.row_number}:"
                    f"segment_prefix={segment_date_prefix}:timestamp_date={timestamp_date}"
                )

        if state == "Patient positioning & induction":
            seen_positioning_state = True

        out.append(
            StateLabeledEvent(
                case_id=event.case_id,
                timestamp=event.timestamp,
                event_type=event.event_type,
                segment_id=event.segment_id,
                event_kind=event.event_kind,
                source=event.source,
                is_synthetic=event.is_synthetic,
                source_detail=event.source_detail,
                insertion_rule=event.insertion_rule,
                row_number=event.row_number,
                state=state,
                state_assignment_rule=state_assignment_rule,
                cleanup_rule_applied=";".join(cleanup_rules_applied) if cleanup_rules_applied else "",
                drop_reason=event.drop_reason,
                raw_payload=deepcopy(event.raw_payload),
            )
        )

    return out, warnings
