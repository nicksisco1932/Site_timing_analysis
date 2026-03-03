#!/usr/bin/env python
"""
Shared workflow constants for the TULSA timing pipeline.
"""

from __future__ import annotations


STATE_ORDER = [
    "TULSA QA",
    "Room ready",
    "Patient positioning & induction",
    "Device insertion",
    "Device repositioning",
    "Alignment",
    "Coarse",
    "Detailed",
    "Planning start angle",
    "Initialization",
    "Treating",
    "Paused",
    "Review",
    "Post-treatment scans & Device removal",
    "Patient recovery & transfer",
    "NA",
]


PLOTTED_STATES = [state for state in STATE_ORDER if state != "NA"]


STATE_COLORS = {
    "TULSA QA": "#d9d9d9",
    "Room ready": "#b3b3b3",
    "Patient positioning & induction": "#8c8c8c",
    "Device insertion": "#9bcd9b",
    "Device repositioning": "#698b69",
    "Alignment": "#add8e6",
    "Coarse": "#4169e1",
    "Detailed": "#27408b",
    "Planning start angle": "#000080",
    "Initialization": "#eedd82",
    "Treating": "#daa520",
    "Paused": "#b8860b",
    "Review": "#8b6508",
    "Post-treatment scans & Device removal": "#c1ffc1",
    "Patient recovery & transfer": "#8b7b8b",
    "NA": "#ffffff",
}
