<!--
Project: Site Timing Analysis
File: tools/profoundtools/UPSTREAM.md
Primary author: Nicholas J. Sisco, Ph.D.
Organization: Profound Medical, LLC
Created: 2026-08-11
Purpose: Records provenance and integration boundaries for the local ProfoundTools Sync transport snapshot.

Provenance: Integration documentation maintained by Nicholas J. Sisco, Ph.D.
for Profound Medical, LLC; the vendored source remains attributed to its
original ProfoundTools authors.

Rights status: Proprietary / internal use unless otherwise specified by
Profound Medical, LLC.
-->

# ProfoundTools Sync Transport Snapshot

This directory contains the unmodified `Python/sync-tdc-logs` subtree from:

- Upstream archive: `profoundmedical-profoundtools-3b561f41388e.zip`
- Upstream revision: `3b561f41388e`
- Archive SHA-256: `B438F35D72D30D794D228D17B40E9B667C409F6DC3D5F36DF2E9882951664C85`
- Local transport root: `tools/profoundtools`

Timeline Analysis uses this snapshot only as the read-only Sync.com transport
for explicitly selected acquisition work. The existing planner and `applog`
workflow are unchanged.

The original multi-project archive is retained locally as `upstream.zip` and is
ignored by Git. Real `sites.json`, saved plans, download staging, partial files,
credentials, clinical databases, and generated acquisition outputs must not be
committed.
