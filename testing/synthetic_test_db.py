# Project: Site Timing Analysis
# File: testing/synthetic_test_db.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-10
# Purpose: Builds a deterministic synthetic SQLite fixture for pipeline tests.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

"""Create a minimal, non-clinical SQLite database for integration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SYNTHETIC_CASE_ID = "SYNTHETIC_999"

_SYNTHETIC_EVENTS = (
    (1, "SetupWorkflowRecord", "2026-01-01 08:00:00"),
    (2, "UATestRecord", "2026-01-01 08:10:00"),
    (3, "AnesthesiaStart", "2026-01-01 08:20:00"),
    (4, "DeviceInsertionBegins", "2026-01-01 08:30:00"),
    (5, "DeviceInsertionEnds", "2026-01-01 08:40:00"),
    (6, "InitialImaging", "2026-01-01 08:50:00"),
    (7, "PSHomingRecord", "2026-01-01 09:00:00"),
    (8, "AlignmentWorkflowRecord", "2026-01-01 09:10:00"),
    (9, "CoarseWorkflowRecord", "2026-01-01 09:20:00"),
    (10, "DetailedWorkflowRecord", "2026-01-01 09:30:00"),
    (11, "PlanReadyWorkflowRecord", "2026-01-01 09:40:00"),
    (12, "DeliveryInitializingWorkflowRecord", "2026-01-01 09:50:00"),
    (13, "DeliveryWorkflowRecord", "2026-01-01 10:00:00"),
    (14, "DeliveryPausedWorkflowRecord", "2026-01-01 10:10:00"),
    (15, "DeliveryResumedWorkflowRecord", "2026-01-01 10:20:00"),
    (16, "DeliveryInterruptedWorkflowRecord", "2026-01-01 10:30:00"),
    (17, "ReviewWorkflowRecord", "2026-01-01 10:40:00"),
    (18, "DevicesRemovalEnds", "2026-01-01 10:50:00"),
    (19, "PatientTransferBegins", "2026-01-01 11:00:00"),
    (20, "PatientTransferEnds", "2026-01-01 12:10:00"),
)


def create_synthetic_test_db(path: Path, *, overwrite: bool = False) -> Path:
    """Create and return a deterministic SQLite fixture at ``path``.

    Inputs:
        ``path`` is the generated database location. ``overwrite`` permits
        replacement only when the caller explicitly identifies the file as a
        disposable test artifact.
    Output:
        The resolved fixture path.
    Assumptions:
        Event identifiers, timestamps, and patient identity are invented for
        test coverage and do not originate from a source clinical database.
    """

    db_path = Path(path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        if not overwrite:
            raise FileExistsError(f"Synthetic test database already exists: {db_path}")
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE AuditLogRecords (
                Id INTEGER PRIMARY KEY,
                AuditRecordBase_Type TEXT NOT NULL,
                EventKind INTEGER,
                TimeStamp TEXT NOT NULL,
                TreatmentId TEXT,
                PatientId TEXT NOT NULL
            );

            CREATE TABLE Sessions (
                Id INTEGER PRIMARY KEY,
                PatientId TEXT,
                DisplayName TEXT,
                FirstName TEXT,
                LastName TEXT,
                TimePatientSedatedAt TEXT,
                TimeUaInsertedAt TEXT,
                TimePatientTransferredAt TEXT
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO AuditLogRecords (
                Id,
                AuditRecordBase_Type,
                TimeStamp,
                PatientId
            ) VALUES (?, ?, ?, ?)
            """,
            [(*event, SYNTHETIC_CASE_ID) for event in _SYNTHETIC_EVENTS],
        )
        connection.commit()
    finally:
        connection.close()

    return db_path
