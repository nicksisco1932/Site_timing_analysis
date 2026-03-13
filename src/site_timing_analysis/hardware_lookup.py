from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import HardwareLookupError


MINIMUM_SOURCE_TABLES: tuple[str, ...] = (
    "AuditLogRecords",
    "DynamicRecords",
    "DynamicElementRecords",
    "HardwareInfoRecords",
    "HardwareInfoElementRecords",
    "SignalMessage",
    "HardwareTestData",
    "HardwareTestResults",
    "ElementPowerReflections",
    "RFAmplifierCalibrationDatas",
    "Sessions",
    "Treatments",
    "PlanningDatas",
    "ThermometryScanHeaders",
    "Issues",
    "LinearMeasurements",
    "PersistablePoints",
    "RfAmplifierUnderperformingOccurrences",
)

_DIRECT_PS_CABLE_FIELDS: tuple[str, ...] = (
    "PSCableSerialNumber",
    "PsCableSerialNumber",
    "PSCableSerial",
    "PsCableSerial",
    "CableSerialNumber",
)
_INFERRED_PS_SERIAL_FIELDS: tuple[str, ...] = ("PSSerialNumber", "PSSerial")
_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+_\d{2}-\d{3}$")


@dataclass(slots=True)
class CaseDbInput:
    case_id: str
    db_path: Path
    site_code: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_case_id(case_id: str) -> str:
    normalized = str(case_id).strip()
    if not normalized:
        raise HardwareLookupError("case_id is required for hardware ingestion.")
    return normalized


def _normalize_site_code(site_code: str | None, case_id: str) -> str:
    if site_code is not None and str(site_code).strip():
        return str(site_code).strip()
    prefix = str(case_id).split("_", 1)[0].strip()
    if prefix:
        return prefix
    return "unknown"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _to_float(value: Any) -> float | None:
    text = _safe_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_bool(value: Any) -> bool:
    text = _safe_text(value).lower()
    return text in {"1", "true", "yes", "y"}


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise HardwareLookupError(f"Failed to open source db read-only [{db_path}]: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _connect_lookup_rw(lookup_db_path: Path) -> sqlite3.Connection:
    lookup_db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(lookup_db_path)
    except sqlite3.Error as exc:
        raise HardwareLookupError(f"Failed to open lookup db [{lookup_db_path}]: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()
    return [str(row[1]) for row in rows]


def _table_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS c FROM [{table_name}]").fetchone()
    return int(row["c"]) if row is not None else 0


def _select_rows(
    conn: sqlite3.Connection,
    table_name: str,
    desired_columns: list[str],
) -> list[dict[str, Any]]:
    available = _table_columns(conn, table_name)
    selected = [col for col in desired_columns if col in available]
    if not selected:
        return []
    query = "SELECT " + ", ".join(f"[{col}]" for col in selected) + f" FROM [{table_name}]"
    return [dict(row) for row in conn.execute(query).fetchall()]


def _ensure_lookup_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingest_batches (
            ingest_batch_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            note TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ingested_cases (
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            source_db_path TEXT NOT NULL,
            source_db_size_bytes INTEGER NOT NULL,
            source_db_mtime TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            status TEXT NOT NULL,
            warning TEXT NOT NULL,
            PRIMARY KEY (ingest_batch_id, case_id)
        );

        CREATE TABLE IF NOT EXISTS source_table_inventory (
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            columns_csv TEXT NOT NULL,
            PRIMARY KEY (ingest_batch_id, case_id, table_name)
        );

        CREATE TABLE IF NOT EXISTS case_treatment_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            session_id TEXT,
            treatment_id TEXT,
            session_uid TEXT,
            treatment_uid TEXT,
            patient_id TEXT,
            session_start TEXT,
            treatment_start TEXT,
            source_table TEXT NOT NULL,
            source_row_id TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hardware_identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            session_id TEXT,
            treatment_id TEXT,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_column TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            confidence TEXT NOT NULL,
            note TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_device_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            session_id TEXT,
            treatment_id TEXT,
            metric_name TEXT NOT NULL,
            metric_value TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_field TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            note TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_hardware_summary (
            ingest_batch_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            site_code TEXT NOT NULL,
            ps_cable_serial_answer TEXT NOT NULL,
            answer_type TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_field TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            source_value TEXT NOT NULL,
            note TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (ingest_batch_id, case_id)
        );

        CREATE INDEX IF NOT EXISTS idx_ingested_cases_case_id
            ON ingested_cases (case_id);
        CREATE INDEX IF NOT EXISTS idx_hardware_identifiers_case_id
            ON hardware_identifiers (case_id, identifier_type);
        CREATE INDEX IF NOT EXISTS idx_case_hardware_summary_case_id
            ON case_hardware_summary (case_id);
        """
    )


def _reset_case_rows(conn: sqlite3.Connection, ingest_batch_id: str, case_id: str) -> None:
    for table_name in (
        "ingested_cases",
        "source_table_inventory",
        "case_treatment_context",
        "hardware_identifiers",
        "case_device_metrics",
        "case_hardware_summary",
    ):
        conn.execute(
            f"DELETE FROM [{table_name}] WHERE ingest_batch_id = ? AND case_id = ?",
            (ingest_batch_id, case_id),
        )


def _insert_inventory_rows(
    conn: sqlite3.Connection,
    *,
    ingest_batch_id: str,
    case_id: str,
    source_tables: list[str],
    source_conn: sqlite3.Connection,
) -> None:
    for table_name in source_tables:
        row_count = _table_row_count(source_conn, table_name)
        columns = _table_columns(source_conn, table_name)
        conn.execute(
            """
            INSERT INTO source_table_inventory (
                ingest_batch_id, case_id, table_name, row_count, columns_csv
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (ingest_batch_id, case_id, table_name, row_count, ",".join(columns)),
        )


def _append_identifier(
    identifiers: list[dict[str, Any]],
    *,
    case_id: str,
    site_code: str,
    session_id: str,
    treatment_id: str,
    identifier_type: str,
    identifier_value: Any,
    source_table: str,
    source_column: str,
    source_row_id: str,
    confidence: str,
    note: str,
) -> None:
    text_value = _safe_text(identifier_value)
    if not text_value:
        return
    identifiers.append(
        {
            "case_id": case_id,
            "site_code": site_code,
            "session_id": session_id,
            "treatment_id": treatment_id,
            "identifier_type": identifier_type,
            "identifier_value": text_value,
            "source_table": source_table,
            "source_column": source_column,
            "source_row_id": source_row_id,
            "confidence": confidence,
            "note": note,
        }
    )


def _extract_context_and_identifiers(
    *,
    case_id: str,
    site_code: str,
    source_conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables = set(_table_names(source_conn))
    contexts: list[dict[str, Any]] = []
    identifiers: list[dict[str, Any]] = []

    sessions_rows = (
        _select_rows(
            source_conn,
            "Sessions",
            [
                "Id",
                "Uid",
                "PatientId",
                "Start",
                "SessionState",
            ],
        )
        if "Sessions" in tables
        else []
    )
    treatments_rows = (
        _select_rows(
            source_conn,
            "Treatments",
            [
                "Id",
                "Uid",
                "SessionId",
                "Start",
                "PSSerialNumber",
                "PSTestDataId",
                "UATestDataId",
                "TreatmentControllerVersion",
                "PSSerial",
                "PSCableSerialNumber",
                "PsCableSerialNumber",
                "CableSerialNumber",
            ],
        )
        if "Treatments" in tables
        else []
    )
    sessions_by_id = {_safe_text(row.get("Id")): row for row in sessions_rows}
    treatments_by_test_id: dict[tuple[str, str], dict[str, Any]] = {}

    for row in treatments_rows:
        row_id = _safe_text(row.get("Id")) or "unknown"
        session_id = _safe_text(row.get("SessionId"))
        treatment_id = _safe_text(row.get("Id"))
        session_row = sessions_by_id.get(session_id, {})
        contexts.append(
            {
                "session_id": session_id,
                "treatment_id": treatment_id,
                "session_uid": _safe_text(session_row.get("Uid")),
                "treatment_uid": _safe_text(row.get("Uid")),
                "patient_id": _safe_text(session_row.get("PatientId")),
                "session_start": _safe_text(session_row.get("Start")),
                "treatment_start": _safe_text(row.get("Start")),
                "source_table": "Treatments",
                "source_row_id": row_id,
            }
        )

        for key in ("PSTestDataId", "UATestDataId"):
            test_value = _safe_text(row.get(key))
            if test_value:
                treatments_by_test_id[(key, test_value)] = row

        for field in _DIRECT_PS_CABLE_FIELDS:
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id=session_id,
                treatment_id=treatment_id,
                identifier_type="ps_cable_serial_number",
                identifier_value=row.get(field),
                source_table="Treatments",
                source_column=field,
                source_row_id=row_id,
                confidence="direct",
                note="direct_ps_cable_serial_field",
            )

        for field in _INFERRED_PS_SERIAL_FIELDS:
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id=session_id,
                treatment_id=treatment_id,
                identifier_type="ps_serial_number",
                identifier_value=row.get(field),
                source_table="Treatments",
                source_column=field,
                source_row_id=row_id,
                confidence="inferred",
                note="fallback_ps_serial_number_from_treatments",
            )

        _append_identifier(
            identifiers,
            case_id=case_id,
            site_code=site_code,
            session_id=session_id,
            treatment_id=treatment_id,
            identifier_type="ps_test_data_id",
            identifier_value=row.get("PSTestDataId"),
            source_table="Treatments",
            source_column="PSTestDataId",
            source_row_id=row_id,
            confidence="direct",
            note="treatment_link_field",
        )
        _append_identifier(
            identifiers,
            case_id=case_id,
            site_code=site_code,
            session_id=session_id,
            treatment_id=treatment_id,
            identifier_type="ua_test_data_id",
            identifier_value=row.get("UATestDataId"),
            source_table="Treatments",
            source_column="UATestDataId",
            source_row_id=row_id,
            confidence="direct",
            note="treatment_link_field",
        )

    if not treatments_rows:
        for row in sessions_rows:
            row_id = _safe_text(row.get("Id")) or "unknown"
            contexts.append(
                {
                    "session_id": _safe_text(row.get("Id")),
                    "treatment_id": "",
                    "session_uid": _safe_text(row.get("Uid")),
                    "treatment_uid": "",
                    "patient_id": _safe_text(row.get("PatientId")),
                    "session_start": _safe_text(row.get("Start")),
                    "treatment_start": "",
                    "source_table": "Sessions",
                    "source_row_id": row_id,
                }
            )

    if "HardwareTestResults" in tables:
        test_rows = _select_rows(
            source_conn,
            "HardwareTestResults",
            ["Id", "PSTestDataId", "UATestDataId", "UASerial", "PSSerialNumber", "PSSerial", "PsModel"],
        )
        for row in test_rows:
            row_id = _safe_text(row.get("Id")) or "unknown"
            mapped_treatment = None
            for key in ("PSTestDataId", "UATestDataId"):
                test_value = _safe_text(row.get(key))
                if test_value and (key, test_value) in treatments_by_test_id:
                    mapped_treatment = treatments_by_test_id[(key, test_value)]
                    break

            session_id = _safe_text(mapped_treatment.get("SessionId")) if mapped_treatment else ""
            treatment_id = _safe_text(mapped_treatment.get("Id")) if mapped_treatment else ""

            for field in _DIRECT_PS_CABLE_FIELDS:
                _append_identifier(
                    identifiers,
                    case_id=case_id,
                    site_code=site_code,
                    session_id=session_id,
                    treatment_id=treatment_id,
                    identifier_type="ps_cable_serial_number",
                    identifier_value=row.get(field),
                    source_table="HardwareTestResults",
                    source_column=field,
                    source_row_id=row_id,
                    confidence="direct",
                    note="direct_ps_cable_serial_field",
                )
            for field in _INFERRED_PS_SERIAL_FIELDS:
                _append_identifier(
                    identifiers,
                    case_id=case_id,
                    site_code=site_code,
                    session_id=session_id,
                    treatment_id=treatment_id,
                    identifier_type="ps_serial_number",
                    identifier_value=row.get(field),
                    source_table="HardwareTestResults",
                    source_column=field,
                    source_row_id=row_id,
                    confidence="inferred",
                    note="fallback_ps_serial_number_from_hardware_test_results",
                )
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id=session_id,
                treatment_id=treatment_id,
                identifier_type="ua_serial",
                identifier_value=row.get("UASerial"),
                source_table="HardwareTestResults",
                source_column="UASerial",
                source_row_id=row_id,
                confidence="direct",
                note="ua_serial_from_hardware_test_results",
            )
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id=session_id,
                treatment_id=treatment_id,
                identifier_type="ps_model",
                identifier_value=row.get("PsModel"),
                source_table="HardwareTestResults",
                source_column="PsModel",
                source_row_id=row_id,
                confidence="direct",
                note="ps_model_from_hardware_test_results",
            )

    if "RFAmplifierCalibrationDatas" in tables:
        calibration_rows = _select_rows(
            source_conn,
            "RFAmplifierCalibrationDatas",
            ["Id", "PowerReflectionHardwareTestResultId", "UATestDataId", "Element"],
        )
        for row in calibration_rows:
            row_id = _safe_text(row.get("Id")) or "unknown"
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id="",
                treatment_id="",
                identifier_type="power_reflection_test_result_id",
                identifier_value=row.get("PowerReflectionHardwareTestResultId"),
                source_table="RFAmplifierCalibrationDatas",
                source_column="PowerReflectionHardwareTestResultId",
                source_row_id=row_id,
                confidence="direct",
                note="rf_calibration_link",
            )
            _append_identifier(
                identifiers,
                case_id=case_id,
                site_code=site_code,
                session_id="",
                treatment_id="",
                identifier_type="ua_test_data_id",
                identifier_value=row.get("UATestDataId"),
                source_table="RFAmplifierCalibrationDatas",
                source_column="UATestDataId",
                source_row_id=row_id,
                confidence="direct",
                note="rf_calibration_link",
            )

    return contexts, identifiers


def _extract_case_metrics(
    *,
    case_id: str,
    site_code: str,
    source_conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    tables = set(_table_names(source_conn))
    metrics: list[dict[str, Any]] = []

    def add_metric(
        *,
        session_id: str,
        treatment_id: str,
        metric_name: str,
        metric_value: Any,
        source_table: str,
        source_field: str,
        source_row_id: str,
        note: str,
    ) -> None:
        text_value = _safe_text(metric_value)
        if text_value == "":
            return
        metrics.append(
            {
                "case_id": case_id,
                "site_code": site_code,
                "session_id": session_id,
                "treatment_id": treatment_id,
                "metric_name": metric_name,
                "metric_value": text_value,
                "source_table": source_table,
                "source_field": source_field,
                "source_row_id": source_row_id,
                "note": note,
            }
        )

    if "HardwareInfoRecords" in tables:
        rows = _select_rows(
            source_conn,
            "HardwareInfoRecords",
            ["Id", "TreatmentId", "TimeStamp", "UaPressurePsi", "EcdPressurePsi", "AmplifierState"],
        )
        add_metric(
            session_id="",
            treatment_id="",
            metric_name="hardware_info_row_count",
            metric_value=len(rows),
            source_table="HardwareInfoRecords",
            source_field="*",
            source_row_id="all",
            note="count_rows",
        )

        ua_values = [value for value in (_to_float(row.get("UaPressurePsi")) for row in rows) if value is not None]
        ecd_values = [value for value in (_to_float(row.get("EcdPressurePsi")) for row in rows) if value is not None]
        if ua_values:
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="ua_pressure_min_psi",
                metric_value=min(ua_values),
                source_table="HardwareInfoRecords",
                source_field="UaPressurePsi",
                source_row_id="all",
                note="aggregated_min",
            )
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="ua_pressure_max_psi",
                metric_value=max(ua_values),
                source_table="HardwareInfoRecords",
                source_field="UaPressurePsi",
                source_row_id="all",
                note="aggregated_max",
            )
        if ecd_values:
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="ecd_pressure_min_psi",
                metric_value=min(ecd_values),
                source_table="HardwareInfoRecords",
                source_field="EcdPressurePsi",
                source_row_id="all",
                note="aggregated_min",
            )
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="ecd_pressure_max_psi",
                metric_value=max(ecd_values),
                source_table="HardwareInfoRecords",
                source_field="EcdPressurePsi",
                source_row_id="all",
                note="aggregated_max",
            )

        state_counts = Counter(_safe_text(row.get("AmplifierState")) for row in rows if _safe_text(row.get("AmplifierState")))
        if state_counts:
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="amplifier_state_counts_json",
                metric_value=json.dumps(dict(sorted(state_counts.items())), sort_keys=True),
                source_table="HardwareInfoRecords",
                source_field="AmplifierState",
                source_row_id="all",
                note="aggregated_counter",
            )

    if "DynamicRecords" in tables:
        rows = _select_rows(
            source_conn,
            "DynamicRecords",
            ["Id", "TreatmentId", "TimeStamp", "TreatmentState", "RotationVelocity"],
        )
        add_metric(
            session_id="",
            treatment_id="",
            metric_name="dynamic_record_row_count",
            metric_value=len(rows),
            source_table="DynamicRecords",
            source_field="*",
            source_row_id="all",
            note="count_rows",
        )
        states = Counter(_safe_text(row.get("TreatmentState")) for row in rows if _safe_text(row.get("TreatmentState")))
        if states:
            add_metric(
                session_id="",
                treatment_id="",
                metric_name="dynamic_treatment_state_counts_json",
                metric_value=json.dumps(dict(sorted(states.items())), sort_keys=True),
                source_table="DynamicRecords",
                source_field="TreatmentState",
                source_row_id="all",
                note="aggregated_counter",
            )

    if "ElementPowerReflections" in tables:
        rows = _select_rows(
            source_conn,
            "ElementPowerReflections",
            ["Id", "IsHighReflection", "IsHighAmplitude", "IsNoForwardPower"],
        )
        add_metric(
            session_id="",
            treatment_id="",
            metric_name="high_reflection_count",
            metric_value=sum(1 for row in rows if _to_bool(row.get("IsHighReflection"))),
            source_table="ElementPowerReflections",
            source_field="IsHighReflection",
            source_row_id="all",
            note="aggregated_count_true",
        )
        add_metric(
            session_id="",
            treatment_id="",
            metric_name="high_amplitude_count",
            metric_value=sum(1 for row in rows if _to_bool(row.get("IsHighAmplitude"))),
            source_table="ElementPowerReflections",
            source_field="IsHighAmplitude",
            source_row_id="all",
            note="aggregated_count_true",
        )

    if "RFAmplifierCalibrationDatas" in tables:
        rows = _select_rows(source_conn, "RFAmplifierCalibrationDatas", ["Id"])
        add_metric(
            session_id="",
            treatment_id="",
            metric_name="rf_calibration_row_count",
            metric_value=len(rows),
            source_table="RFAmplifierCalibrationDatas",
            source_field="*",
            source_row_id="all",
            note="count_rows",
        )

    return metrics


def _select_best_ps_cable_answer(case_id: str, identifiers: list[dict[str, Any]]) -> dict[str, str]:
    direct_candidates = [
        row for row in identifiers if row["identifier_type"] == "ps_cable_serial_number"
    ]
    if direct_candidates:
        chosen = sorted(
            direct_candidates,
            key=lambda row: (row["source_table"], row["source_column"], row["source_row_id"]),
        )[0]
        return {
            "case_id": case_id,
            "ps_cable_serial_answer": chosen["identifier_value"],
            "answer_type": "direct",
            "source_table": chosen["source_table"],
            "source_field": chosen["source_column"],
            "source_row_id": chosen["source_row_id"],
            "source_value": chosen["identifier_value"],
            "note": "direct_ps_cable_serial_field",
        }

    inferred_candidates = [
        row for row in identifiers if row["identifier_type"] == "ps_serial_number"
    ]
    source_priority = {
        ("Treatments", "PSSerialNumber"): 1,
        ("Treatments", "PSSerial"): 2,
        ("HardwareTestResults", "PSSerialNumber"): 3,
        ("HardwareTestResults", "PSSerial"): 4,
    }
    if inferred_candidates:
        chosen = sorted(
            inferred_candidates,
            key=lambda row: (
                source_priority.get((row["source_table"], row["source_column"]), 999),
                row["source_row_id"],
            ),
        )[0]
        return {
            "case_id": case_id,
            "ps_cable_serial_answer": chosen["identifier_value"],
            "answer_type": "inferred",
            "source_table": chosen["source_table"],
            "source_field": chosen["source_column"],
            "source_row_id": chosen["source_row_id"],
            "source_value": chosen["identifier_value"],
            "note": "inferred_from_ps_serial_field",
        }

    return {
        "case_id": case_id,
        "ps_cable_serial_answer": "",
        "answer_type": "missing",
        "source_table": "",
        "source_field": "",
        "source_row_id": "",
        "source_value": "",
        "note": "no_ps_cable_or_ps_serial_identifier_found",
    }


def _ingest_single_case(
    *,
    lookup_conn: sqlite3.Connection,
    ingest_batch_id: str,
    case: CaseDbInput,
) -> dict[str, Any]:
    case_id = _normalize_case_id(case.case_id)
    site_code = _normalize_site_code(case.site_code, case_id)
    db_path = case.db_path.expanduser().resolve()
    if not db_path.exists():
        raise HardwareLookupError(f"[{case_id}] source db does not exist: {db_path}")

    with _connect_read_only(db_path) as source_conn:
        source_tables = _table_names(source_conn)
        contexts, identifiers = _extract_context_and_identifiers(
            case_id=case_id,
            site_code=site_code,
            source_conn=source_conn,
        )
        metrics = _extract_case_metrics(
            case_id=case_id,
            site_code=site_code,
            source_conn=source_conn,
        )

        _reset_case_rows(lookup_conn, ingest_batch_id, case_id)
        _insert_inventory_rows(
            lookup_conn,
            ingest_batch_id=ingest_batch_id,
            case_id=case_id,
            source_tables=source_tables,
            source_conn=source_conn,
        )

    source_stat = db_path.stat()
    lookup_conn.execute(
        """
        INSERT INTO ingested_cases (
            ingest_batch_id, case_id, site_code, source_db_path, source_db_size_bytes,
            source_db_mtime, ingested_at, status, warning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ingest_batch_id,
            case_id,
            site_code,
            str(db_path),
            int(source_stat.st_size),
            datetime.fromtimestamp(source_stat.st_mtime, tz=timezone.utc).isoformat(),
            _utc_now_iso(),
            "ingested",
            "",
        ),
    )

    for context in contexts:
        lookup_conn.execute(
            """
            INSERT INTO case_treatment_context (
                ingest_batch_id, case_id, site_code, session_id, treatment_id, session_uid,
                treatment_uid, patient_id, session_start, treatment_start, source_table, source_row_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ingest_batch_id,
                case_id,
                site_code,
                context["session_id"],
                context["treatment_id"],
                context["session_uid"],
                context["treatment_uid"],
                context["patient_id"],
                context["session_start"],
                context["treatment_start"],
                context["source_table"],
                context["source_row_id"],
            ),
        )

    for row in identifiers:
        lookup_conn.execute(
            """
            INSERT INTO hardware_identifiers (
                ingest_batch_id, case_id, site_code, session_id, treatment_id, identifier_type,
                identifier_value, source_table, source_column, source_row_id, confidence, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ingest_batch_id,
                row["case_id"],
                row["site_code"],
                row["session_id"],
                row["treatment_id"],
                row["identifier_type"],
                row["identifier_value"],
                row["source_table"],
                row["source_column"],
                row["source_row_id"],
                row["confidence"],
                row["note"],
            ),
        )

    for row in metrics:
        lookup_conn.execute(
            """
            INSERT INTO case_device_metrics (
                ingest_batch_id, case_id, site_code, session_id, treatment_id, metric_name,
                metric_value, source_table, source_field, source_row_id, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ingest_batch_id,
                row["case_id"],
                row["site_code"],
                row["session_id"],
                row["treatment_id"],
                row["metric_name"],
                row["metric_value"],
                row["source_table"],
                row["source_field"],
                row["source_row_id"],
                row["note"],
            ),
        )

    answer = _select_best_ps_cable_answer(case_id, identifiers)
    lookup_conn.execute(
        """
        INSERT INTO case_hardware_summary (
            ingest_batch_id, case_id, site_code, ps_cable_serial_answer, answer_type,
            source_table, source_field, source_row_id, source_value, note, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ingest_batch_id,
            case_id,
            site_code,
            answer["ps_cable_serial_answer"],
            answer["answer_type"],
            answer["source_table"],
            answer["source_field"],
            answer["source_row_id"],
            answer["source_value"],
            answer["note"],
            _utc_now_iso(),
        ),
    )

    return {
        "case_id": case_id,
        "site_code": site_code,
        "status": "ingested",
        "source_db_path": str(db_path),
        "identifier_count": len(identifiers),
        "metric_count": len(metrics),
        "answer_type": answer["answer_type"],
    }


def _derive_case_id_from_db_path(db_path: Path, root_hint: Path | None = None) -> str:
    if root_hint is not None:
        try:
            relative = db_path.resolve().relative_to(root_hint.resolve())
            for part in relative.parts:
                if _CASE_ID_PATTERN.fullmatch(part):
                    return part
        except ValueError:
            pass
    for part in db_path.resolve().parts[::-1]:
        if _CASE_ID_PATTERN.fullmatch(part):
            return part
    return db_path.parent.name


def discover_case_databases(site_root: Path) -> list[CaseDbInput]:
    root = site_root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HardwareLookupError(f"site_root is missing or not a directory: {root}")

    seen: set[tuple[str, str]] = set()
    cases: list[CaseDbInput] = []
    for db_path in sorted(root.rglob("local.db"), key=lambda p: str(p).lower()):
        case_id = _derive_case_id_from_db_path(db_path, root)
        key = (case_id, str(db_path.resolve()))
        if key in seen:
            continue
        seen.add(key)
        cases.append(CaseDbInput(case_id=case_id, db_path=db_path.resolve(), site_code=None))
    return cases


def _parse_case_db_arg(value: str) -> CaseDbInput:
    text = str(value).strip()
    if "=" not in text:
        raise HardwareLookupError(
            f"Invalid --case-db value '{value}'. Expected format: <case_id>=<path_to_local.db>"
        )
    case_id, path_text = text.split("=", 1)
    case_id = _normalize_case_id(case_id)
    db_path = Path(path_text.strip()).expanduser().resolve()
    return CaseDbInput(case_id=case_id, db_path=db_path, site_code=None)


def _write_batch_summary_exports(
    *,
    lookup_conn: sqlite3.Connection,
    ingest_batch_id: str,
    output_dir: Path,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_csv_path = output_dir / "hardware_case_hardware_summary.csv"
    ps_audit_csv_path = output_dir / "hardware_ps_cable_answer_audit.csv"
    md_path = output_dir / "hardware_lookup_ingest_summary.md"

    rows = lookup_conn.execute(
        """
        SELECT ingest_batch_id, case_id, site_code, ps_cable_serial_answer, answer_type,
               source_table, source_field, source_row_id, source_value, note, generated_at
        FROM case_hardware_summary
        WHERE ingest_batch_id = ?
        ORDER BY case_id
        """,
        (ingest_batch_id,),
    ).fetchall()
    if rows:
        with summary_csv_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        with ps_audit_csv_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = [
                "case_id",
                "answer_type",
                "ps_cable_serial_answer",
                "source_table",
                "source_field",
                "source_row_id",
                "source_value",
                "note",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "case_id": row["case_id"],
                        "answer_type": row["answer_type"],
                        "ps_cable_serial_answer": row["ps_cable_serial_answer"],
                        "source_table": row["source_table"],
                        "source_field": row["source_field"],
                        "source_row_id": row["source_row_id"],
                        "source_value": row["source_value"],
                        "note": row["note"],
                    }
                )
    else:
        summary_csv_path.write_text("", encoding="utf-8")
        ps_audit_csv_path.write_text("", encoding="utf-8")

    case_counts = lookup_conn.execute(
        """
        SELECT status, COUNT(*) AS c
        FROM ingested_cases
        WHERE ingest_batch_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (ingest_batch_id,),
    ).fetchall()
    answer_counts = lookup_conn.execute(
        """
        SELECT answer_type, COUNT(*) AS c
        FROM case_hardware_summary
        WHERE ingest_batch_id = ?
        GROUP BY answer_type
        ORDER BY answer_type
        """,
        (ingest_batch_id,),
    ).fetchall()
    lines = [
        "# Hardware Lookup Ingest Summary",
        "",
        f"- ingest_batch_id: `{ingest_batch_id}`",
        f"- summary_csv: `{summary_csv_path}`",
        f"- ps_answer_audit_csv: `{ps_audit_csv_path}`",
        "",
        "## Case Status Counts",
    ]
    if case_counts:
        for row in case_counts:
            lines.append(f"- {row['status']}: {row['c']}")
    else:
        lines.append("- none")
    lines.extend(["", "## PS Cable Answer Types"])
    if answer_counts:
        for row in answer_counts:
            lines.append(f"- {row['answer_type']}: {row['c']}")
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "summary_csv": str(summary_csv_path),
        "ps_answer_audit_csv": str(ps_audit_csv_path),
        "ingest_summary_md": str(md_path),
    }


def ingest_local_dbs(
    *,
    lookup_db_path: Path,
    cases: list[CaseDbInput],
    ingest_batch_id: str | None = None,
    note: str = "",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not cases:
        raise HardwareLookupError("No cases provided for hardware lookup ingestion.")

    batch_id = ingest_batch_id.strip() if ingest_batch_id is not None else f"hw_{uuid4()}"
    if not batch_id:
        raise HardwareLookupError("ingest_batch_id cannot be blank.")

    lookup_path = lookup_db_path.expanduser().resolve()
    out_dir = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else lookup_path.parent / "hardware_lookup_outputs" / batch_id
    )

    with _connect_lookup_rw(lookup_path) as lookup_conn:
        _ensure_lookup_schema(lookup_conn)
        lookup_conn.execute(
            """
            INSERT OR REPLACE INTO ingest_batches (ingest_batch_id, created_at, note)
            VALUES (?, ?, ?)
            """,
            (batch_id, _utc_now_iso(), _safe_text(note)),
        )

        ingested = 0
        failed = 0
        case_results: list[dict[str, Any]] = []
        for case in sorted(cases, key=lambda c: c.case_id.lower()):
            case_id = _normalize_case_id(case.case_id)
            try:
                result = _ingest_single_case(
                    lookup_conn=lookup_conn,
                    ingest_batch_id=batch_id,
                    case=case,
                )
                case_results.append(result)
                ingested += 1
            except Exception as exc:
                failed += 1
                warning_text = str(exc)
                lookup_conn.execute(
                    """
                    INSERT OR REPLACE INTO ingested_cases (
                        ingest_batch_id, case_id, site_code, source_db_path, source_db_size_bytes,
                        source_db_mtime, ingested_at, status, warning
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        case_id,
                        _normalize_site_code(case.site_code, case_id),
                        str(case.db_path.expanduser().resolve()),
                        0,
                        "",
                        _utc_now_iso(),
                        "failed",
                        warning_text,
                    ),
                )
                case_results.append(
                    {
                        "case_id": case_id,
                        "status": "failed",
                        "error": warning_text,
                    }
                )
        export_paths = _write_batch_summary_exports(
            lookup_conn=lookup_conn,
            ingest_batch_id=batch_id,
            output_dir=out_dir,
        )
        lookup_conn.commit()

    return {
        "lookup_db_path": str(lookup_path),
        "ingest_batch_id": batch_id,
        "cases_requested": len(cases),
        "cases_ingested": ingested,
        "cases_failed": failed,
        "case_results": case_results,
        "exports": export_paths,
    }


def _resolve_query_batch_id(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    ingest_batch_id: str | None,
) -> str | None:
    if ingest_batch_id is not None and ingest_batch_id.strip():
        return ingest_batch_id.strip()
    row = conn.execute(
        """
        SELECT ingest_batch_id
        FROM ingested_cases
        WHERE case_id = ? AND status = 'ingested'
        ORDER BY ingested_at DESC
        LIMIT 1
        """,
        (case_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["ingest_batch_id"])


def query_ps_cable_serial(
    *,
    lookup_db_path: Path,
    case_id: str,
    ingest_batch_id: str | None = None,
) -> dict[str, Any]:
    normalized_case_id = _normalize_case_id(case_id)
    with _connect_lookup_rw(lookup_db_path.expanduser().resolve()) as conn:
        _ensure_lookup_schema(conn)
        resolved_batch_id = _resolve_query_batch_id(
            conn,
            case_id=normalized_case_id,
            ingest_batch_id=ingest_batch_id,
        )
        if resolved_batch_id is None:
            return {
                "case_id": normalized_case_id,
                "ingest_batch_id": "",
                "question": "ps_cable_serial",
                "answer": "",
                "answer_type": "missing",
                "source_table": "",
                "source_field": "",
                "source_row_id": "",
                "source_value": "",
                "inference": "missing",
                "note": "no_ingested_case_found",
                "provenance_candidates": [],
            }

        summary = conn.execute(
            """
            SELECT case_id, ingest_batch_id, ps_cable_serial_answer, answer_type,
                   source_table, source_field, source_row_id, source_value, note
            FROM case_hardware_summary
            WHERE ingest_batch_id = ? AND case_id = ?
            """,
            (resolved_batch_id, normalized_case_id),
        ).fetchone()
        if summary is None:
            return {
                "case_id": normalized_case_id,
                "ingest_batch_id": resolved_batch_id,
                "question": "ps_cable_serial",
                "answer": "",
                "answer_type": "missing",
                "source_table": "",
                "source_field": "",
                "source_row_id": "",
                "source_value": "",
                "inference": "missing",
                "note": "case_summary_missing_for_ingested_case",
                "provenance_candidates": [],
            }

        provenance_rows = conn.execute(
            """
            SELECT identifier_type, identifier_value, source_table, source_column,
                   source_row_id, confidence, note
            FROM hardware_identifiers
            WHERE ingest_batch_id = ? AND case_id = ?
              AND identifier_type IN ('ps_cable_serial_number', 'ps_serial_number')
            ORDER BY source_table, source_column, source_row_id
            """,
            (resolved_batch_id, normalized_case_id),
        ).fetchall()
        provenance = [dict(row) for row in provenance_rows]
        return {
            "case_id": normalized_case_id,
            "ingest_batch_id": resolved_batch_id,
            "question": "ps_cable_serial",
            "answer": summary["ps_cable_serial_answer"],
            "answer_type": summary["answer_type"],
            "source_table": summary["source_table"],
            "source_field": summary["source_field"],
            "source_row_id": summary["source_row_id"],
            "source_value": summary["source_value"],
            "inference": summary["answer_type"],
            "note": summary["note"],
            "provenance_candidates": provenance,
        }


def _write_query_audit(result: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Hardware Query Audit",
        "",
        f"- case_id: `{result['case_id']}`",
        f"- ingest_batch_id: `{result['ingest_batch_id']}`",
        f"- question: `{result['question']}`",
        f"- answer: `{result['answer']}`",
        f"- answer_type: `{result['answer_type']}`",
        f"- source_table: `{result['source_table']}`",
        f"- source_field: `{result['source_field']}`",
        f"- source_row_id: `{result['source_row_id']}`",
        f"- note: `{result['note']}`",
        "",
        "## Provenance Candidates",
    ]
    candidates = result.get("provenance_candidates", [])
    if candidates:
        for row in candidates:
            lines.append(
                "- "
                + f"{row['identifier_type']}={row['identifier_value']} "
                + f"(source={row['source_table']}.{row['source_column']} row={row['source_row_id']} "
                + f"confidence={row['confidence']})"
            )
    else:
        lines.append("- none")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a case-indexed hardware lookup database from local.db files "
            "and answer structured hardware questions with provenance."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest one or more local.db files.")
    ingest_parser.add_argument("--lookup-db", required=True, help="Target hardware lookup sqlite path.")
    ingest_parser.add_argument("--ingest-batch-id", default=None, help="Optional deterministic batch id.")
    ingest_parser.add_argument("--note", default="", help="Optional ingest note.")
    ingest_parser.add_argument("--output-dir", default=None, help="Optional output directory for audit artifacts.")
    ingest_parser.add_argument(
        "--case-db",
        action="append",
        default=[],
        help="Explicit case mapping in format <case_id>=<path_to_local.db>. Can be repeated.",
    )
    ingest_parser.add_argument(
        "--site-root",
        action="append",
        default=[],
        help="Root directory to scan recursively for local.db files. Can be repeated.",
    )
    ingest_parser.add_argument(
        "--site-code",
        default=None,
        help="Optional site code applied to discovered cases when not derivable from case_id.",
    )

    query_parser = subparsers.add_parser("query", help="Query a case-level hardware answer.")
    query_parser.add_argument("--lookup-db", required=True, help="Hardware lookup sqlite path.")
    query_parser.add_argument("--case-id", required=True, help="Case identifier to query.")
    query_parser.add_argument(
        "--question",
        default="ps-cable-serial",
        choices=["ps-cable-serial"],
        help="Structured hardware question to answer.",
    )
    query_parser.add_argument("--ingest-batch-id", default=None, help="Optional specific ingest batch id.")
    query_parser.add_argument("--audit-output", default=None, help="Optional markdown audit output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "ingest":
        explicit_cases = [_parse_case_db_arg(item) for item in args.case_db]
        discovered_cases: list[CaseDbInput] = []
        for root_text in args.site_root:
            discovered_cases.extend(discover_case_databases(Path(root_text)))

        all_cases = [*explicit_cases, *discovered_cases]
        if args.site_code is not None and str(args.site_code).strip():
            all_cases = [
                CaseDbInput(case_id=case.case_id, db_path=case.db_path, site_code=str(args.site_code).strip())
                for case in all_cases
            ]

        result = ingest_local_dbs(
            lookup_db_path=Path(args.lookup_db),
            cases=all_cases,
            ingest_batch_id=args.ingest_batch_id,
            note=args.note,
            output_dir=Path(args.output_dir) if args.output_dir is not None else None,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "query":
        if args.question != "ps-cable-serial":
            raise HardwareLookupError(f"Unsupported question: {args.question}")
        result = query_ps_cable_serial(
            lookup_db_path=Path(args.lookup_db),
            case_id=args.case_id,
            ingest_batch_id=args.ingest_batch_id,
        )
        if args.audit_output is not None:
            audit_path = _write_query_audit(result, Path(args.audit_output).expanduser().resolve())
            result["audit_output"] = str(audit_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    raise HardwareLookupError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
