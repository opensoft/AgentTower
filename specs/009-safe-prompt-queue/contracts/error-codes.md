# Closed-Set CLI / Socket Error Codes

**Branch**: `009-safe-prompt-queue`
**Surface**: Every FEAT-009 CLI subcommand and every FEAT-009 socket method MAY return one of the codes below. The list is closed (FR-049).

## Full vocabulary

| String code                       | First-introduced by | Used in                                                                 |
|-----------------------------------|---------------------|-------------------------------------------------------------------------|
| `approval_not_applicable`         | FEAT-009            | `queue approve` when block_reason is intrinsic or kill switch off.       |
| `bad_request`                     | FEAT-002 (existing) | Any malformed request envelope.                                          |
| `body_empty`                      | FEAT-009            | `send-input` body has length 0.                                          |
| `body_invalid_chars`              | FEAT-009            | `send-input` body contains NUL or disallowed ASCII control.              |
| `body_invalid_encoding`           | FEAT-009            | `send-input` body is not valid UTF-8.                                    |
| `body_too_large`                  | FEAT-009            | Serialized envelope exceeds the configured cap.                          |
| `daemon_shutting_down`            | FEAT-009            | Daemon is in shutdown (FR-049).                                          |
| `daemon_unavailable`              | FEAT-001 (existing) | Socket unreachable.                                                      |
| `delay_not_applicable`            | FEAT-009            | `queue delay` on already-blocked row.                                    |
| `delivery_in_progress`            | FEAT-009            | Operator action on a row mid-flight.                                     |
| `delivery_wait_timeout`           | FEAT-009            | `send-input` wait budget elapsed; row still non-terminal.                |
| `kill_switch_off`                 | FEAT-009            | Row's `block_reason` value; the CLI translates to `routing_disabled`.    |
| `routing_disabled`                | FEAT-009            | `send-input` CLI exit code mapped from `block_reason=kill_switch_off`.   |
| `routing_toggle_host_only`        | FEAT-009            | `routing enable` / `disable` from a bench container (Q2).                |
| `sender_not_in_pane`              | FEAT-009            | Host-side `send-input` rejected (Q3).                                    |
| `sender_role_not_permitted`       | FEAT-009            | Sender pane resolves to non-master or inactive sender.                   |
| `since_invalid_format`            | FEAT-009            | `--since` cannot be parsed as ISO-8601 UTC.                              |
| `target_container_inactive`       | FEAT-009            | Target container gone (enqueue or re-check).                             |
| `target_label_ambiguous`          | FEAT-009            | `--target` matches multiple active labels.                               |
| `target_not_active`               | FEAT-009            | Target marked inactive (enqueue or re-check).                            |
| `target_not_found`                | FEAT-009            | `--target` resolves to nothing OR `message_id` unknown.                  |
| `target_pane_missing`             | FEAT-009            | Target pane missing (enqueue or re-check).                               |
| `target_role_not_permitted`       | FEAT-009            | Target role not in `{slave, swarm}`.                                     |
| `terminal_state_cannot_change`    | FEAT-009            | Operator action on a terminal row.                                       |
| `unknown_method`                  | FEAT-002 (existing) | Socket method not registered.                                            |

Total: 25 codes. Eleven are introduced by FEAT-009 (the rest reuse
or specialize existing FEAT-001..008 codes). All are added to the
`CLOSED_CODE_SET` frozen set in `src/agenttower/socket_api/errors.py`.

## kill_switch_off vs routing_disabled

The two codes are distinct on purpose:

- `kill_switch_off` is the *row-state* `block_reason` value stored in
  `message_queue.block_reason` and emitted in JSONL audit `reason`
  field. It describes *why the row is blocked*.
- `routing_disabled` is the *CLI exit code* for `send-input` when
  the row was blocked at enqueue with `kill_switch_off`. It describes
  *the operator-visible outcome of the CLI invocation*.

A consumer scripting `send-input` branches on `routing_disabled`;
a consumer reading `events.jsonl` branches on `kill_switch_off`.

## Stable contract vs integer exit codes

Per FR-050, the string codes above are the stable contract. The
integer exit codes in the CLI may shift across MVP revisions and
are documented in each `cli-*.md` contract file as the *current*
mapping; tooling should branch on the `--json` `block_reason` /
`failure_reason` / wrapping error envelope `code` field, not on
integer exit codes.

## Integer exit code map (MVP)

| Integer | String code(s)                                                                          |
|---------|-----------------------------------------------------------------------------------------|
| `0`     | success                                                                                  |
| `1`     | `delivery_wait_timeout`                                                                  |
| `2`     | `routing_disabled` (CLI mapping of `kill_switch_off`)                                    |
| `3`     | `sender_not_in_pane`                                                                     |
| `4`     | `sender_role_not_permitted`                                                              |
| `5`     | `target_not_found`                                                                       |
| `6`     | `target_label_ambiguous`                                                                 |
| `7`     | `target_not_active`                                                                      |
| `8`     | `target_role_not_permitted`                                                              |
| `9`     | `target_container_inactive`                                                              |
| `10`    | `target_pane_missing`                                                                    |
| `11`    | `body_empty` / `body_invalid_encoding` / `body_invalid_chars` / `body_too_large`         |
| `12`    | `daemon_unavailable` / `daemon_shutting_down`                                            |
| `13`    | other terminal failures (`tmux_paste_failed`, `docker_exec_failed`, `tmux_send_keys_failed`, `pane_disappeared_mid_attempt`, `attempt_interrupted`) |
| `14`    | `since_invalid_format`                                                                   |
| `15`    | `terminal_state_cannot_change`                                                           |
| `16`    | `delivery_in_progress`                                                                   |
| `17`    | `approval_not_applicable`                                                                |
| `18`    | `delay_not_applicable`                                                                   |
| `19`    | `routing_toggle_host_only`                                                               |
| `64`    | `bad_request` / `unknown_method` (argparse usage-style)                                  |

This map is also encoded as a constant
`CLI_EXIT_CODE_MAP: Final[dict[str, int]]` in
`src/agenttower/routing/errors.py` so test fixtures and
documentation share a single source of truth.
