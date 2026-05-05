# Contract: User-Facing CLI (FEAT-001)

**Branch**: `001-package-state-foundation` | **Date**: 2026-05-05

This contract is the externally-observable surface that FEAT-001 ships.
Every behavior listed here is reachable via `subprocess.run` from a test
harness; nothing here depends on Python in-process imports.

The contract covers exactly two console scripts (`agenttower`,
`agenttowerd`), four invocations (`--version`, `--help`, `config paths`,
`config init`) on the user CLI, and one invocation (`--version`) on the
daemon CLI. Anything not listed below is **out of scope for FEAT-001**.

---

## C-CLI-001 — `agenttower --version`

### Invocation

```bash
agenttower --version
```

### Behavior

Prints the resolved package version to **stdout**, then exits.

### Output (stdout)

Exactly one line:

```text
agenttower <VERSION>
```

Where `<VERSION>` matches `importlib.metadata.version("agenttower")`. For
a development install of the FEAT-001 release, `<VERSION>` is `0.1.0`.
For uninstalled source-tree execution, the fallback `0.0.0+local` may
appear.

### Output (stderr)

None.

### Exit code

`0`.

### Side effects

None. Does not read or create any file under the resolved path set.

---

## C-CLI-002 — `agenttower --help`

### Invocation

```bash
agenttower --help
agenttower -h
agenttower            # no arguments → same usage text, exit 0
```

### Behavior

Prints argparse-rendered usage text to **stdout** and exits.

### Output (stdout)

Must contain, at minimum (substring matches, line order not asserted):

- `usage: agenttower`
- `--version`
- `config`
- (under the `config` subcommand block) `paths`
- (under the `config` subcommand block) `init`

### Exit code

`0`.

### Side effects

None.

---

## C-CLI-003 — `agenttower config paths`

### Invocation

```bash
agenttower config paths
```

### Behavior

Resolves the Resolved Path Set from the current environment (no XDG
overrides honored unless set on the calling shell) and prints each path.
Does **not** create files or directories — output is identical whether
or not `config init` has run.

### Output (stdout)

Exactly six lines, in this fixed order, each in `KEY=value` form with no
surrounding whitespace and no quoting:

```text
CONFIG_FILE=<absolute path>
STATE_DB=<absolute path>
EVENTS_FILE=<absolute path>
LOGS_DIR=<absolute path>
SOCKET=<absolute path>
CACHE_DIR=<absolute path>
```

Each `value` is an absolute filesystem path. No path contains a literal
`=`, newline, single quote, or double quote (paths come from XDG /
`$HOME` resolution and are normalized via `pathlib.Path`).

### Output (stderr)

If AgentTower has **not** yet been initialized (the `STATE_DB` file does
not exist), one informational line is printed to **stderr**, exactly:

```text
note: agenttower has not been initialized; run `agenttower config init`
```

When initialized (the `STATE_DB` file exists), nothing is written to
stderr.

### Exit code

`0` in both initialized and uninitialized states.

### Side effects

None. Path-only side-effect-free.

### Parseability invariant

`eval "$(agenttower config paths)"` MUST set the six environment
variables `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`,
`SOCKET`, `CACHE_DIR` to their respective absolute paths in any POSIX
shell, with no further escaping required.

---

## C-CLI-004 — `agenttower config init`

### Invocation

```bash
agenttower config init
```

### Behavior

Creates the durable Opensoft layout idempotently. On a fresh host:

1. Creates each missing directory among the configuration directory
   (parent of `CONFIG_FILE`), the state directory (parent of
   `STATE_DB`), `LOGS_DIR`, `CACHE_DIR`, and any intermediate
   `opensoft/` parent that the command creates, with mode `0700`.
2. Creates `CONFIG_FILE` with the default content (see
   `data-model.md` §2 and `research.md` R-005), mode `0600`, **only if**
   the file does not already exist.
3. Opens / creates `STATE_DB` (mode `0600` on first creation), applies
   `journal_mode=WAL` and `foreign_keys=ON`, ensures the
   `schema_version(version INTEGER NOT NULL)` table exists, and
   inserts the integer `1` (the current `CURRENT_SCHEMA_VERSION`)
   **only if** the table is empty.
   Any SQLite companion files created by the call are set to mode
   `0600`.
4. Does NOT create `EVENTS_FILE`. Does NOT create `SOCKET`. Does NOT
   touch any pre-existing log file, socket file, event history file, or
   other artifact in the resolved paths.

If a required pre-existing AgentTower-owned artifact that this command
must read or write has a broader mode than required by FR-015, the command
fails with exit code `1`, prints the path-specific error shape below, and
leaves the artifact byte-identical.

### Output (stdout)

Exactly two lines on first run (when something was created):

```text
created config: <CONFIG_FILE absolute path>
created registry: <STATE_DB absolute path>
```

On idempotent re-run (everything already exists), exactly two lines:

```text
already initialized: <CONFIG_FILE absolute path>
already initialized: <STATE_DB absolute path>
```

When mixed (e.g. config newly written, db pre-existed), each line uses
the `created` or `already initialized` prefix appropriate to its
artifact independently.

### Output (stderr)

On the success path (exit `0`): empty.

On failure (exit non-zero): a single line of the form:

```text
error: <action verb>: <absolute path>: <reason>
```

For example:

```text
error: create directory: /nonwritable/.config/opensoft/agenttower: Permission denied
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (created or idempotent no-op). |
| `1` | Filesystem error (unwritable parent, permission denied, etc.). |
| `1` | SQLite error (corrupt existing DB, lock failure). |
| `1` | Permission-mode refusal for a required pre-existing AgentTower-owned artifact. |

There is exactly one non-success exit code in FEAT-001 (`1`). Subdivision
into more codes is left to later features that need to distinguish
classes of failure programmatically.

### Side effects on success

- Directories created with mode `0700`, including intermediate
  `opensoft/` parents created by the command.
- Files created with mode `0600`, including SQLite companion files created
  by the command.
- Required pre-existing AgentTower-owned artifacts are used only when their
  modes are no broader than required; otherwise the command fails without
  mutating them.
- Unrelated pre-existing artifacts are left untouched.
- Nothing written to `EVENTS_FILE` (per FR-016 and Q4).
- No network listener opened. No daemon started. No Docker / tmux call
  made.

### Side effects on failure

- No partially-initialized `STATE_DB` left behind for the current failing
  call: the SQLite file and any companion files created during that call
  are either fully initialized (table + row) or absent.
- A partially-created directory tree may exist (e.g. the config dir was
  created before the state dir failed); subsequent `config init`
  invocations MUST be able to complete the tree without errors. This
  satisfies the spec's "previous run was interrupted and only some
  directories exist" edge case.
- Stderr names the offending path.

### Idempotence contract (FR-010)

After any successful `config init`:

- Re-running `config init` exits `0`.
- `CONFIG_FILE` byte content is unchanged.
- `STATE_DB` continues to contain exactly one row in `schema_version`
  with the same `version` value.
- The directory layout is unchanged (mtime may or may not change; this
  contract does not assert mtime stability).

---

## C-CLI-005 — `agenttowerd --version`

### Invocation

```bash
agenttowerd --version
```

### Behavior

Identical contract to C-CLI-001 except that the program name in the
output line is `agenttowerd`.

### Output (stdout)

```text
agenttowerd <VERSION>
```

Where `<VERSION>` is byte-equal to the `<VERSION>` value reported by
`agenttower --version` from the same install.

### Exit code

`0`.

### Side effects

None. Does **not** start the daemon, **not** open the socket, and
**not** write any state. (Daemon lifecycle is owned by FEAT-002.)

### Behavior for any other invocation

Out of scope for FEAT-001. Any subcommand or flag not listed in this
contract MAY exit non-zero with a placeholder error in this feature
release; FEAT-002 owns the full daemon CLI surface.

---

## Cross-cutting CLI guarantees (FR-014, FR-016)

- All FEAT-001 invocations produce **no records** in `EVENTS_FILE` (per
  Q4 / FR-016). The presence/size of `EVENTS_FILE` after running any of
  the above must be unchanged (or absent if pre-absent).
- All failures exit non-zero with stderr that names the offending path
  or cause (FR-014).
- No invocation listed above opens a network socket, calls Docker, calls
  tmux, registers an agent, or attaches a log (FR-016).
- All paths printed or operated on resolve to absolute paths under the
  user's `opensoft/agenttower` namespace (FR-006/FR-007).
