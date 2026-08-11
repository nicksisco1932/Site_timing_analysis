# AI Agent Operating Protocol

This document defines the rules and workflow for AI coding agents operating in this repository.

Agents must read and follow this file before performing any analysis, modification, or code generation.

## Control File Read Order

For non-trivial tasks, agents must read repository control files in this order:

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md` (if present)
4. `SESSION.md` (if present)
5. task-specific files

`AGENTS.md` defines rules and constraints. `SOP.md` defines process.

## Core Principles

This repository prioritizes:

- Deterministic behavior
- Minimal-scope changes
- Reproducible debugging
- Auditability of transformations
- Preservation of legacy behavior during refactors

Agents must behave as junior engineers working under strict architectural guidance.

Human developers remain the final decision authority.

## Mandatory Workflow

Agents must follow this sequence for any non-trivial task.

### 1. Understand the Objective

Before writing or modifying code:

- Identify the goal of the task
- Identify relevant modules
- Identify dependencies
- Identify assumptions

If the objective is unclear, stop and ask for clarification.

### 2. Perform System Audit

Before modifying legacy code, the agent must first analyze:

- Input contracts
- Output contracts
- Pipeline stages
- Dependencies
- Implicit assumptions
- Error handling
- Side effects

Legacy behavior must be documented before attempting to reproduce or modify it.

### 3. Decompose the Task

Agents must break problems into explicit steps.

Example structure:

- Discovery
- Validation
- Parsing
- Transformation
- Aggregation
- Export

Each stage must have:

- Defined inputs
- Defined outputs
- Clearly bounded logic

### 4. Minimize Scope of Changes

Agents must never perform drive-by refactors.

Rules:

- Modify only files necessary for the task
- Do not rename modules unless explicitly instructed
- Do not reorganize directory structures
- Do not change APIs without approval

### 5. Preserve Legacy Behavior

When refactoring legacy code:

- Reproduce behavior before optimizing
- Preserve output formats
- Preserve ordering semantics
- Preserve time calculations

Parity must be verified before improvements.

### 6. Explicit Error Handling

New code must not silently fail.

Prefer:

- Explicit exceptions
- Validation checks
- Diagnostic logging

Avoid silent coercion or implicit type conversion.

## Refactoring Guidelines

When converting legacy systems:

Required strategy:

1. Audit
2. Architecture
3. Implementation
4. Validation

Agents must not jump directly from audit to full rewrite.

### Refactor Targets

Prefer modular design.

Example Python pipeline layout:

```text
pipeline/
    discovery.py
    validation.py
    ingestion.py
    transformation.py
    aggregation.py
    export.py
```

Each module should have a single responsibility.

## Database Handling

Many workflows interact with `local.db` SQLite databases.

Agents must:

- Treat schema assumptions carefully
- Extract SQL queries explicitly
- Document tables and columns used
- Avoid destructive writes

Read-only access is preferred during analysis.

## Path and Environment Rules

Agents must avoid hard-coded paths.

Use:

- Relative paths
- Configuration files
- Environment variables

Example:

- `config.yaml` for pipeline configuration

## Python Execution Environment (Mandatory)

All Python execution in this repository must use the repo-local virtual environment: `.venv`.

Rules:

- Do not rely on activated-shell state.
- Do not assume `.venv` is active.
- Never use bare commands: `python`, `pip`, `pytest`.
- Always use explicit `.venv` executables.

Required command forms:

- `.\.venv\Scripts\python.exe -m pytest ...`
- `.\.venv\Scripts\python.exe -m <module> ...`
- `.\.venv\Scripts\python.exe <script.py> ...`
- `.\.venv\Scripts\pip.exe install ...`

If `.venv` is missing or invalid, stop and report it clearly before running Python commands.

## Logging

All non-trivial scripts should include logging.

Minimum standard:

- `INFO`  - major pipeline stage
- `DEBUG` - detailed processing
- `WARN`  - recoverable anomalies
- `ERROR` - failures

## Testing and Validation

Before major refactors:

- Identify reference outputs
- Capture baseline behavior
- Validate new pipeline against baseline

Agents should recommend minimal validation datasets when possible.

## Code Style Expectations

Python code should prioritize:

- Readability
- Explicitness
- Functional modularity

Avoid:

- Deeply nested logic
- Hidden state
- Global variables
- Implicit side effects

## Safe Modification Rules

Agents must not:

- Delete legacy code without approval
- Overwrite reference scripts
- Modify datasets
- Modify external dependencies

Legacy code should remain available for comparison.

## Documentation Requirements

Any significant logic introduced by an agent must include:

- Function docstrings
- Input/output descriptions
- Assumptions
- Known limitations

## Standing Order: Source Authorship and Provenance Headers

Source-file provenance is a repository governance requirement. This repository
contains code developed by Nicholas J. Sisco, Ph.D. in the course of work for
Profound Medical, LLC. Headers should preserve human authorship and
implementation provenance while accurately reflecting the company-owned /
proprietary context.

- New source files must include a concise, language-appropriate provenance
  header.
- Existing source headers must be preserved.
- Agents must not remove, weaken, anonymize, or overwrite provenance,
  authorship, copyright, license, or proprietary notices.
- When Nicholas J. Sisco, Ph.D. authored or materially implemented a source
  file, the header must identify Nicholas J. Sisco, Ph.D. as the primary author
  or implementer.
- Headers must identify Profound Medical, LLC as the rights holder /
  proprietary context, not Nicholas J. Sisco personally.
- Do not make unsupported legal ownership claims.
- Do not add headers to generated artifacts, logs, exported data,
  DICOM-derived outputs, archives, binary files, build outputs, cache files, or
  vendored third-party dependencies.
- Third-party notices must be retained exactly as found.
- If third-party or pre-existing code is modified, add a modification note
  rather than replacing the original notice.
- Before completing any coding task, agents should check whether newly created
  or materially modified source files contain the required header.
- AI tools are not to be listed as authors in source headers. AI assistance may
  be mentioned in commit messages or implementation notes if useful, but file
  headers should identify the responsible human author/maintainer and
  organizational context.

Preferred default header template for Python files:

```python
# Project: Site Timing Analysis
# File: <RELATIVE_FILE_PATH>
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: <YYYY-MM-DD or Unknown>
# Purpose: <ONE-SENTENCE PURPOSE>
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
```

Preferred generic comment template:

```text
Project: Site Timing Analysis
File: <RELATIVE_FILE_PATH>
Primary author: Nicholas J. Sisco, Ph.D.
Organization: Profound Medical, LLC
Created: <YYYY-MM-DD or Unknown>
Purpose: <ONE-SENTENCE PURPOSE>

Provenance: Original implementation or material contribution by
Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.

Rights status: Proprietary / internal use unless otherwise specified
by Profound Medical, LLC.
```

## When the Agent Must Stop

Agents must stop and ask for guidance when:

- Task intent is unclear
- Behavior cannot be inferred from code
- Multiple architectural approaches are possible
- Legacy behavior appears inconsistent

## Expected Agent Behavior

Agents should behave as:

- Careful
- Conservative
- Explicit
- Reproducible

Not as:

- Speculative
- Overly creative
- Overly broad in modifications

## Summary

The goal of this protocol is to ensure that AI assistance produces:

- Reliable engineering outcomes
- Reproducible pipelines
- Safe refactors of legacy systems

Agents must follow these rules for all work performed in this repository.
