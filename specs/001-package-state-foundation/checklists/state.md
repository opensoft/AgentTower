# State & Schema Durability Checklist: Package, Config, and State Foundation

**Purpose**: Pre-implementation requirements gate for the `STATE_DB` / `schema_version` surface — validates that every requirement governing the SQLite registry's creation, idempotence, durability, and forward-compatibility is complete, clear, consistent, measurable, and traceable BEFORE `/speckit.implement` runs.
**Created**: 2026-05-05
**Feature**: [spec.md](../spec.md), [plan.md](../plan.md), [data-model.md](../data-model.md) §3, [research.md](../research.md) R-006, [contracts/cli.md](../contracts/cli.md) C-CLI-004
**Depth**: Strict pre-implementation gate — every item must be resolved (or explicitly accepted as out of scope) before T011/T012/T013/T014 begin.
**Audience**: Spec author, peer reviewer, and compliance reviewer (mixed).

**Note**: This checklist tests the REQUIREMENTS, not the implementation. Each item asks whether the requirement is well-written — complete, clear, consistent, measurable, and unambiguous. Items end with `[Quality dimension, traceability]` where traceability is either a spec section reference or one of the markers `[Gap]`, `[Ambiguity]`, `[Conflict]`, `[Assumption]`.

## Requirement Completeness

- [ ] CHK001 - Are all `config init` SQLite-side steps (parent dir create, file create, file mode, PRAGMA application, table create, row insert) enumerated in a single canonical location? [Completeness, Spec §FR-005, §FR-009, Plan R-006]
- [ ] CHK002 - Is the recovery requirement specified for the case where `STATE_DB` exists but the `schema_version` table is missing (e.g. file truncated, table dropped externally)? [Coverage, Gap]
- [ ] CHK003 - Is the recovery requirement specified for the case where `schema_version` exists but contains zero rows after a prior interrupted insert? [Coverage, Recovery Flow, Spec §FR-010, Gap]
- [ ] CHK004 - Is the behavior specified for the case where `schema_version` exists with more than one row (corrupted prior state)? [Coverage, Gap]
- [ ] CHK005 - Is the behavior specified when `STATE_DB` exists but is not a valid SQLite file (e.g. zero bytes left from a prior partial init)? [Coverage, Exception Flow, Gap, Spec §FR-014]
- [ ] CHK006 - Are requirements documented for stale SQLite WAL companion files (`-wal`, `-shm`) found in the state directory at init time? [Coverage, Gap]
- [ ] CHK007 - Are concurrent `agenttower config init` invocations addressed (two shells racing for the same `STATE_DB`)? [Coverage, Gap, Plan §Constraints "Single host user"]
- [ ] CHK008 - Is the "no partial DB on failure" requirement defined precisely — which file is removed, by whom, and only if this run created it? [Completeness, Contracts §C-CLI-004 "Side effects on failure"]
- [ ] CHK009 - Is the schema-migration boundary explicitly documented as out of scope for FEAT-001, with a forward-pointer to the feature that owns it? [Completeness, Spec §Assumptions, Plan §Summary]
- [ ] CHK010 - Are PRAGMA application requirements (`journal_mode=WAL`, `foreign_keys=ON`) specified as idempotent on every open, and is the spec/plan explicit about whether they are reapplied on every connection or only at init time? [Completeness, Plan R-006]
- [ ] CHK011 - Is the relationship between `STATE_DB` creation (FR-005) and `EVENTS_FILE` non-creation (Spec §"What FEAT-001 deliberately does NOT do", Q4) documented in one place so a reviewer cannot confuse the two artifacts? [Completeness, Spec §FR-016, Quickstart §11]

## Requirement Clarity

- [ ] CHK012 - Is "current schema generation" defined with a specific integer constant exposed by the package (e.g. `CURRENT_SCHEMA_VERSION`), rather than implied? [Clarity, Spec §FR-009, Data-Model §3.1]
- [ ] CHK013 - Is the decoupling between `schema_version.version` and the package release version stated explicitly in spec.md AND consistently echoed in plan / data-model / research? [Clarity, Spec §FR-009, Data-Model §3.1]
- [ ] CHK014 - Is "monotonically increasing integer starting at 1" quantified — does the spec say what triggers an increment (per migration? per release? per FEAT-N?) and which feature owns increment authority? [Clarity, Spec §FR-009, Gap]
- [ ] CHK015 - Is the "exactly one row" invariant tied to a specific enforcement mechanism (CHECK constraint vs. application count-then-insert), and is the chosen mechanism justified? [Clarity, Data-Model §3.1, Plan R-006]
- [ ] CHK016 - Does the spec or plan document whether negative or zero `version` values are valid, given FR-009 says "starting at 1"? [Ambiguity, Spec §FR-009]
- [ ] CHK017 - Is the `schema_version(version INTEGER NOT NULL)` shape unambiguous about whether a `PRIMARY KEY`, `UNIQUE`, or `CHECK` constraint is intentionally absent — or simply unspecified? [Ambiguity, Data-Model §3.1]

## Requirement Consistency

- [ ] CHK018 - Does the `schema_version` DDL match exactly across spec.md (FR-009), data-model.md §3.1, research.md R-006, and contracts/cli.md C-CLI-004 (table name, column name, type, NOT NULL clause, no extra constraints)? [Consistency]
- [ ] CHK019 - Do FR-009 ("contains exactly one row") and FR-010 ("MUST NOT change the recorded schema version") agree on what a re-run does when the table contains **zero** rows (interrupted prior init)? [Consistency, Conflict, Spec §FR-009 vs §FR-010]
- [ ] CHK020 - Do FR-005 ("creates the registry database file") and FR-011 ("MUST NOT delete, truncate, or otherwise mutate any pre-existing … state artifact") consistently handle the case where `STATE_DB` pre-exists but is empty / missing the schema table? [Consistency]
- [ ] CHK021 - Are file-mode requirements for `STATE_DB` consistent between FR-015 (`0600` for files), data-model.md §1 (`0600`), and contracts/cli.md C-CLI-004 ("`0600` on first creation; not chmod'd if pre-existing")? [Consistency, Spec §FR-015]
- [ ] CHK022 - Is the "WAL journal mode" decision in research.md R-006 reconciled with the spec's "no daemon, no second writer in FEAT-001" posture (FR-016) — does the rationale for WAL in FEAT-001 reference forward-compatibility with FEAT-002+ rather than an in-feature need? [Consistency, Plan R-006, Spec §FR-016]
- [ ] CHK023 - Is the spec's "schema migration is explicitly out of scope" statement (Spec §Edge Cases) consistent with R-006's `IF NOT EXISTS` + count-then-insert pattern (i.e. the implementation does not silently migrate either)? [Consistency, Spec §Edge Cases, Plan R-006]

## Acceptance Criteria Quality

- [ ] CHK024 - Is SC-003 ("ten consecutive runs leave registry database file size and schema-version row byte-identical") objectively measurable, including whether SQLite `-wal` / `-shm` companion files count toward "byte-identical"? [Measurability, Spec §SC-003, Gap]
- [ ] CHK025 - Is SC-004 tied to a specific integer literal (`1`) AND sourced from a single named constant so spec drift is detectable in one place? [Measurability, Spec §SC-004, Data-Model §3.1]
- [ ] CHK026 - Does SC-006 ("leaves no partial files behind") define what counts as a "partial file" — `agenttower.sqlite3` only, or also `-journal`, `-wal`, `-shm`, lock files? [Measurability, Spec §SC-006, Gap]
- [ ] CHK027 - Is SC-009's enumeration of "registry database file" sufficient to gate the test, or does the success criterion need to enumerate every state-directory artifact whose mode is asserted (e.g. WAL files inherit DB mode? lock files?)? [Measurability, Spec §SC-009, Gap]

## Scenario & Edge-Case Coverage

- [ ] CHK028 - Are requirements specified for SQLite `SQLITE_BUSY` / `SQLITE_LOCKED` failure paths during init (exit code, stderr shape, retry policy)? [Coverage, Exception Flow, Gap, Spec §FR-014]
- [ ] CHK029 - Are requirements specified for "disk full" mid-INSERT, including whether the resulting partial DB triggers cleanup per FR-014's actionable-error contract? [Coverage, Recovery Flow, Gap]
- [ ] CHK030 - Are requirements specified for `STATE_DB` being a symlink (does init follow, reject, or detect)? [Coverage, Gap]
- [ ] CHK031 - Are requirements specified for filesystems where `fsync` is a no-op (some FUSE / WSL backings) — is durability degraded silently, surfaced in stderr, or out of scope? [Coverage, Gap, Plan R-006]
- [ ] CHK032 - Does the spec address what happens when the parent state directory pre-exists with mode other than `0700` (e.g. `0755` left by a prior tool) — left untouched per FR-015 last sentence, or chmod'd? [Coverage, Spec §FR-015]
- [ ] CHK033 - Are recovery scenarios specified after an init that crashed between `CREATE TABLE` and `INSERT` (table exists, zero rows) — does re-run insert, or detect-and-error? [Recovery Flow, Gap, Spec §FR-010]
- [ ] CHK034 - Is the "previous run was interrupted and only some directories exist" edge case (Spec §Edge Cases) extended explicitly to the SQLite layer, or is it limited to filesystem directories? [Coverage, Ambiguity, Spec §Edge Cases]

## Non-Functional Requirements

- [ ] CHK035 - Is the cold-init performance target "well under one second" (plan.md §Performance Goals) formalized as a measurable success criterion in spec.md, or is it left as plan-level prose only? [Measurability, Gap in Spec §Success Criteria, Plan §Performance Goals]
- [ ] CHK036 - Are durability requirements specified for the `schema_version` row (must INSERT be `fsync`'d before `config init` returns success, or is WAL checkpoint sufficient)? [Completeness, Gap, Plan R-006]
- [ ] CHK037 - Are forward-compatibility requirements documented stating that FEAT-002+ MUST NOT alter the FEAT-001 `schema_version` table shape — only add new tables / columns? [Completeness, Data-Model §3.2]
- [ ] CHK038 - Is the audit / observability requirement for init outcomes ("observable only via stdout and exit code", per Q4) consistent with the schema-durability requirements (no JSONL audit of schema-version state changes)? [Consistency, Spec §Clarifications Q4, §FR-016]

## Dependencies & Assumptions

- [ ] CHK039 - Is a minimum SQLite version specified (relevant because `STRICT` tables, `RETURNING`, certain pragmas depend on ≥3.35; bench images may differ)? [Assumption, Gap, Plan R-006]
- [ ] CHK040 - Is the assumption "FEAT-001 seeds; FEAT-002+ migrates" stated in a single canonical location and traceable from FR-009? [Assumption, Spec §Assumptions]
- [ ] CHK041 - Is the assumption that no other process holds an open SQLite handle on `STATE_DB` during init explicitly documented (consistent with FR-016's "no daemon yet")? [Assumption, Gap, Spec §FR-016]
- [ ] CHK042 - Is the dependency on POSIX file-mode semantics (`0o600` actually being honored by the filesystem, not silently downgraded by mount options) documented? [Assumption, Gap, Spec §FR-015]

## Ambiguities & Conflicts

- [ ] CHK043 - Is "subsequent invocations" in FR-009 ("MUST open cleanly on subsequent invocations") referring to subsequent `config init` runs, subsequent SQLite `connect` calls, or both? [Ambiguity, Spec §FR-009]
- [ ] CHK044 - Does the spec resolve the latent conflict between FR-011 ("MUST NOT mutate any pre-existing state artifact") and FR-009's "MUST insert exactly one row" when a pre-existing DB has zero rows? [Conflict, Spec §FR-009 vs §FR-011]
- [ ] CHK045 - Is the relationship between `schema_version.version`, the package release version (`importlib.metadata.version`), and any future migration-tooling integer made unambiguous in one place? [Ambiguity, Spec §FR-009, Plan R-009]

## Notes

- Resolution policy for this gate: every item must be marked complete (`[x]`) OR replaced with an explicit `[OUT OF SCOPE — accepted by <name>]` note before `/speckit.implement` runs.
- `[Gap]` items SHOULD trigger a spec amendment (re-run `/speckit.specify` or `/speckit.clarify`) unless the gap is intentional and accepted in writing.
- `[Conflict]` and `[Ambiguity]` items MUST be resolved in spec.md before implementation — do not paper over with implementation-side decisions.
- `[Assumption]` items either get promoted to documented assumptions in `Spec §Assumptions` or down-graded to validated facts.
- This checklist evaluates the QUALITY of requirements; behavioral verification (does the code work?) is owned by `tests/unit/test_state_schema.py` (T013) and `tests/integration/test_cli_init.py` (T014).

