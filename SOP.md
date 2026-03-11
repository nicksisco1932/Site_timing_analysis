# SOP.md

## Standard Operating Procedure for Codex Work in This Repository

This document defines the standard operating workflow for AI coding agents working in this repository.

It is intended to preserve continuity, reduce drift across sessions, and support incremental, testable engineering work without sacrificing flexibility.

---

## Purpose

The goal of this SOP is to ensure that AI agents operate as consistent, continuity-aware collaborators rather than stateless code generators.

This SOP exists to:

- preserve session continuity across model changes
- maintain architectural consistency
- reduce repeated rediscovery of prior decisions
- support deterministic, minimal-scope development
- improve handoff quality between AI sessions

---

## Required Read Order

For any non-trivial task, the agent must read files in the following order:

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md`, if present
4. `SESSION.md`, if present
5. any task-specific files explicitly relevant to the request

Examples of task-specific files include:

- `README.md`
- target scripts or modules
- legacy reference files
- test files
- config files

If a required file is missing, the agent must state that clearly and continue only within safe scope.

---

## File Roles

### `AGENTS.md`
Defines repository rules, constraints, behavior, and guardrails.

Examples:
- minimal-scope changes
- no silent refactors
- preserve parity where required
- testing expectations
- stop conditions

### `SOP.md`
Defines the process the agent should follow.

Examples:
- read order
- planning format
- session checkpointing
- handoff expectations
- phase discipline

### `ARCHITECTURE.md`
Defines the intended system structure.

Examples:
- module boundaries
- data flow
- contracts between stages
- accepted abstractions
- implementation roadmap

### `SESSION.md`
Defines the current working state of the project.

Examples:
- what has been implemented
- current objective
- current blocker
- known issues
- next slice to build
- acceptance criteria for the next step

---

## Core Workflow

For non-trivial tasks, agents should follow this sequence:

### 1. Read context
Read the required control files in order.

### 2. Reconstruct state
Determine:
- current objective
- current implementation stage
- known blockers
- applicable constraints
- files likely to be touched

### 3. State plan before editing
Before making changes, provide a short structured plan with:

- files to create
- files to modify
- files guaranteed untouched
- tests to add or update
- acceptance criteria

### 4. Execute minimal-scope work
Make only the changes required for the current slice.

Do not:
- broaden scope without necessity
- perform drive-by refactors
- redesign unrelated modules
- “clean up” legacy behavior unless explicitly approved

### 5. Validate
Run or specify validation appropriate to the task.

Examples:
- unit tests
- smoke tests
- artifact generation
- parity checks
- manual inspection targets

### 6. Report
At the end of each work session, report:

- files created
- files modified
- tests added or updated
- what was implemented
- what was intentionally not implemented
- unresolved assumptions
- recommended next step

### 7. Refresh `SESSION.md`
If the task materially changes project state, update or generate `SESSION.md`.

---

## Session Continuity Protocol

The repository should maintain a lightweight `SESSION.md` file as a rolling checkpoint for AI and human handoff.

### When `SESSION.md` should be updated
Update `SESSION.md` when:
- a new implementation slice is completed
- a blocker is discovered
- the active objective changes
- acceptance criteria are revised
- a handoff to a future session is likely

### What `SESSION.md` should contain
At minimum:

- project name
- current objective
- governing files
- implemented stages
- not-yet-implemented stages
- current blocker
- recent decisions
- known issues
- next recommended step
- resume instructions

### `SESSION.md` should not become
- a diary
- a full design document
- a dump of chain-of-thought
- a replacement for `ARCHITECTURE.md`

It should be concise, operational, and resume-friendly.

---

## Session File Generation Rule

If `SESSION.md` is missing and the task is non-trivial, the agent should generate a minimal `SESSION.md` before or at the end of the task, unless the user explicitly says not to.

If `SESSION.md` exists, the agent should prefer updating it rather than creating a second competing handoff file.

Avoid creating additional handoff files unless explicitly requested by the user. `SESSION.md` remains the canonical current-state checkpoint.

---

## Phase Discipline

Agents must preserve the distinction between these phases:

### Audit
Understand the legacy system or current implementation.

### Design
Define architecture, contracts, and acceptance criteria.

### Implementation
Build only the approved slice.

### Validation
Check correctness, parity, and artifact quality.

### Handoff
Update `SESSION.md` and report status.

Agents must not collapse all phases into one unless explicitly asked.

---

## Flexibility Rule

This SOP is intended to improve continuity, not constrain useful reasoning.

Agents may adapt tactics to the specific task, but must preserve:

- minimal-scope execution
- explicit planning
- clear reporting
- session continuity
- respect for repository contracts

The agent should remain flexible in implementation details while staying disciplined in process.

---

## Recommended `SESSION.md` Template

```markdown
# SESSION.md

## Project
<project name>

## Current Objective
<what is being worked on now>

## Governing Files
- `AGENTS.md`
- `SOP.md`
- `ARCHITECTURE.md`, if present

## Current State
### Implemented
- <implemented slice/module>
- <implemented slice/module>

### Not Yet Implemented
- <next major components>

## Current Blocker
<current blocker, if any>

## Recent Decisions
- <important recent decision>
- <important recent decision>

## Known Issues
- <issue>
- <issue>

## Next Recommended Step
<what should happen next>

## Resume Instructions
1. Read `AGENTS.md`
2. Read `SOP.md`
3. Read `ARCHITECTURE.md`, if present
4. Read `SESSION.md`
5. Continue with <specific next task>
