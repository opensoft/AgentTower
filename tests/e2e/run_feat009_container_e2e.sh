#!/usr/bin/env bash
# FEAT-009 fresh-container end-to-end validation.
#
# Spawns a clean bench container (Opensoft py-bench image), bind-mounts
# the FEAT-009 worktree as /workspace, bind-mounts a fresh daemon socket,
# starts the host daemon, drives:
#
#   1. agenttower register-self inside the container in two panes
#      (master + slave) — exercises the real FEAT-006 in-container
#      identity path (no AGENTTOWER_TEST_PROC_ROOT fake).
#   2. agenttower send-input from the master pane to the slave pane
#      — real tmux paste-buffer delivery (no AGENTTOWER_TEST_TMUX_FAKE).
#   3. tmux capture-pane on the slave pane asserts the body bytes
#      arrived byte-for-byte.
#   4. routing disable + bench-container toggle refusal.
#   5. send-input under disabled → row blocked kill_switch_off, NO
#      paste to the slave pane.
#
# Tear-down is in the EXIT trap so a failure leaves no orphaned
# container or daemon.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Translate sandbox path (/workspace/projects/...) to the
# host-visible path Docker bind-mounts can resolve. WSL2 + the
# claude-code sandbox both see the same files but at different
# absolute paths; the Docker daemon runs at the host level.
host_repo_root="${repo_root/#\/workspace\/projects/\/home\/brett\/projects}"
if [[ "$host_repo_root" == "$repo_root" ]]; then
  # Already host-visible (e.g., running outside the sandbox).
  :
fi

image="${AGENTTOWER_E2E_IMAGE:-py-bench:brett}"
container_name="${AGENTTOWER_E2E_CONTAINER:-agenttower-feat009-e2e}"
session="${AGENTTOWER_E2E_TMUX_SESSION:-feat009-e2e}"
root_dir="${AGENTTOWER_E2E_ROOT:-$repo_root/.tmp/feat009-e2e}"

host_home="$root_dir/home"
xdg_config="$root_dir/xdg/config"
xdg_state="$root_dir/xdg/state"
xdg_cache="$root_dir/xdg/cache"
host_state_dir="$xdg_state/opensoft/agenttower"
host_socket="$host_state_dir/agenttowerd.sock"
host_venv="$root_dir/venv"

container_home="/home/brett"
container_state_dir="$container_home/.local/state/opensoft/agenttower"
container_socket="/run/agenttower/agenttowerd.sock"
container_venv="/tmp/agenttower-venv"
container_path="$container_venv/bin:/home/brett/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

log() {
  printf "\033[36m[e2e]\033[0m %s\n" "$*"
}

fail() {
  printf "\033[31m[e2e:FAIL]\033[0m %s\n" "$*" >&2
  exit 1
}

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

run_host_agenttower() {
  HOME="$host_home" \
  XDG_CONFIG_HOME="$xdg_config" \
  XDG_STATE_HOME="$xdg_state" \
  XDG_CACHE_HOME="$xdg_cache" \
  PATH="$host_venv/bin:$PATH" \
  "$@"
}

# Wrapper for ``agenttower`` inside the bench container (does NOT bind
# the call to any specific tmux pane).
in_container() {
  docker exec "$container_name" sh -lc "PATH='$container_path' $*"
}

# Run a command inside a specific tmux pane (so register-self captures
# the right pane identity).
in_pane() {
  local pane="$1"
  shift
  docker exec "$container_name" sh -lc \
    "tmux send-keys -t '$session:$pane' \"PATH='$container_path' $*\" Enter"
}

teardown() {
  log "tearing down…"
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  if [[ -S "$host_socket" ]]; then
    run_host_agenttower agenttower stop-daemon >/dev/null 2>&1 || true
  fi
  log "tear-down complete"
}

trap teardown EXIT

# ──────────────────────────────────────────────────────────────────────
# Bring-up — host daemon
# ──────────────────────────────────────────────────────────────────────

log "preparing host state dirs under $root_dir"
rm -rf "$root_dir"
mkdir -p "$host_home" "$xdg_config" "$xdg_state" "$xdg_cache"

log "creating host venv + installing agenttower from worktree"
python3 -m venv "$host_venv"
"$host_venv/bin/pip" install --upgrade pip >/dev/null
"$host_venv/bin/pip" install -e "$repo_root[test]" >/dev/null

log "agenttower config init (host)"
run_host_agenttower agenttower config init >/dev/null

log "writing scan config to match container name"
mkdir -p "$xdg_config/opensoft/agenttower"
cat >"$xdg_config/opensoft/agenttower/config.toml" <<EOF
[containers]
name_contains = ["$container_name"]
scan_interval_seconds = 5
EOF

log "ensure-daemon"
run_host_agenttower agenttower ensure-daemon >/dev/null
if [[ ! -S "$host_socket" ]]; then
  fail "host daemon socket missing at $host_socket"
fi
log "host daemon up at $host_socket"

# ──────────────────────────────────────────────────────────────────────
# Bring-up — bench container + tmux session
# ──────────────────────────────────────────────────────────────────────

log "removing any prior container"
docker rm -f "$container_name" >/dev/null 2>&1 || true

log "starting fresh bench container"
# Translate sandbox paths to host-visible paths for Docker bind mounts.
docker_repo_root="${repo_root/#\/workspace\/projects/\/home\/brett\/projects}"
docker_host_state_dir="${host_state_dir/#\/workspace\/projects/\/home\/brett\/projects}"
docker_host_socket="${host_socket/#\/workspace\/projects/\/home\/brett\/projects}"

docker run -d \
  --name "$container_name" \
  --label opensoft.bench=true \
  --label agenttower.feat009-e2e=true \
  -e AGENTTOWER_SOCKET="$container_socket" \
  -e XDG_STATE_HOME="$container_home/.local/state" \
  -e XDG_CONFIG_HOME="$container_home/.config" \
  -e XDG_CACHE_HOME="$container_home/.cache" \
  -e PATH="$container_path" \
  -v "$docker_repo_root:/workspace" \
  -v "$docker_host_state_dir:$container_state_dir" \
  -v "$docker_host_socket:$container_socket" \
  -w /workspace \
  "$image" \
  sleep infinity >/dev/null

log "installing agenttower inside container venv"
docker exec "$container_name" sh -lc \
  "python3 -m venv '$container_venv' && '$container_venv/bin/pip' install --upgrade pip >/dev/null && '$container_venv/bin/pip' install -e /workspace[test] >/dev/null"

log "starting tmux session with master + slave panes"
docker exec "$container_name" sh -lc \
  "tmux kill-session -t '$session' 2>/dev/null || true; \
   tmux new-session -d -s '$session' -n master 'bash --noprofile --norc'; \
   tmux new-window -t '$session' -n slave 'bash --noprofile --norc'"

log "host scan picks up the container + panes"
run_host_agenttower agenttower scan --containers >/dev/null
run_host_agenttower agenttower scan --panes >/dev/null

# ──────────────────────────────────────────────────────────────────────
# Register master + slave from inside their tmux panes
# ──────────────────────────────────────────────────────────────────────

log "register-self in master pane"
in_pane "master" "agenttower register-self --role slave --capability codex --label e2e-master"
# Master role MUST go through set-role per FR-010; register as slave
# first, then promote via set-role.

# Wait briefly for the daemon to record the master agent.
sleep 1.5
master_id="$(run_host_agenttower agenttower list-agents --json | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
# list-agents may or may not wrap in {ok,result}; tolerate either.
agents = data.get('result', data).get('agents', [])
for a in agents:
    if a.get('label') == 'e2e-master':
        print(a['agent_id']); break
")"
if [[ -z "$master_id" ]]; then
  fail "master agent not registered (no agent with label=e2e-master)"
fi
log "master_id=$master_id"

log "promoting master to role=master via set-role"
run_host_agenttower agenttower set-role --target "$master_id" --role master --confirm >/dev/null \
  || fail "set-role master failed"

log "register-self in slave pane"
in_pane "slave" "agenttower register-self --role slave --capability codex --label e2e-slave"
sleep 1.5
slave_id="$(run_host_agenttower agenttower list-agents --json | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
agents = data.get('result', data).get('agents', [])
for a in agents:
    if a.get('label') == 'e2e-slave':
        print(a['agent_id']); break
")"
if [[ -z "$slave_id" ]]; then
  fail "slave agent not registered"
fi
log "slave_id=$slave_id"

# Clear the slave pane history so capture-pane below is unambiguous.
docker exec "$container_name" sh -lc "tmux send-keys -t '$session:slave' 'clear' Enter"
sleep 0.3

# ──────────────────────────────────────────────────────────────────────
# E2E 1 — Real send-input → real tmux paste → capture-pane assertion
# ──────────────────────────────────────────────────────────────────────

probe_message="feat009-e2e-real-tmux-marker-$(date +%s)"

log "send-input from master pane → slave"
docker exec "$container_name" sh -lc \
  "tmux send-keys -t '$session:master' \"PATH='$container_path' agenttower send-input --target $slave_id --message '$probe_message' --no-wait\" Enter"
sleep 3.0

log "capture-pane on slave"
slave_capture="$(docker exec "$container_name" tmux capture-pane -t "$session:slave" -p)"
echo "$slave_capture" | sed 's/^/[slave-pane] /'

if echo "$slave_capture" | grep -Fq "$probe_message"; then
  log "✅ E2E 1: body bytes appear in slave pane history"
else
  fail "E2E 1: probe message NOT found in slave pane history"
fi

# ──────────────────────────────────────────────────────────────────────
# E2E 2 — routing disable from host succeeds; bench refuses
# ──────────────────────────────────────────────────────────────────────

log "routing disable from host"
run_host_agenttower agenttower routing disable >/dev/null
# The CLI prints the daemon's result dict directly (no {ok,result}
# envelope — the FEAT-002 client unwraps that).
status_value="$(run_host_agenttower agenttower routing status --json | python3 -c "
import json, sys; print(json.loads(sys.stdin.read())['value'])")"
[[ "$status_value" == "disabled" ]] || fail "routing status not disabled after host disable: $status_value"
log "✅ E2E 2a: host routing disable accepted"

log "routing disable from bench-container TMUX PANE — should be refused"
# Issue the call from INSIDE the master tmux pane so the CLI's
# resolve_pane_composite_key sees the real TMUX / TMUX_PANE env vars
# and includes caller_pane in the request. Capture the pane after to
# read the exit code line.
docker exec "$container_name" sh -lc \
  "tmux send-keys -t '$session:master' 'clear' Enter; \
   tmux send-keys -t '$session:master' \
     \"PATH='$container_path' agenttower routing disable; echo \\\"RC=\\\$?\\\"\" Enter"
sleep 2.0
bench_capture="$(docker exec "$container_name" tmux capture-pane -t "$session:master" -p)"
echo "$bench_capture" | sed 's/^/[master-pane] /'

if echo "$bench_capture" | grep -Eq "routing[ _]toggle[ _]host[ _]only"; then
  log "✅ E2E 2b: bench-container routing disable refused (routing_toggle_host_only)"
else
  fail "E2E 2b: bench-container routing disable was NOT refused — pane output above"
fi

# ──────────────────────────────────────────────────────────────────────
# E2E 3 — send-input under disabled → blocked kill_switch_off,
# NO paste to slave pane
# ──────────────────────────────────────────────────────────────────────

probe_blocked="feat009-e2e-MUST-NOT-PASTE-$(date +%s)"

log "send-input from master while routing is disabled"
docker exec "$container_name" sh -lc \
  "tmux send-keys -t '$session:master' \"PATH='$container_path' agenttower send-input --target $slave_id --message '$probe_blocked' --no-wait\" Enter"
sleep 2.0

log "capture slave pane — probe should NOT appear"
slave_capture_after_blocked="$(docker exec "$container_name" tmux capture-pane -t "$session:slave" -p)"
if echo "$slave_capture_after_blocked" | grep -Fq "$probe_blocked"; then
  fail "E2E 3: blocked-row body LEAKED into slave pane: '$probe_blocked'"
else
  log "✅ E2E 3a: blocked-row body NOT in slave pane"
fi

# Inspect queue listing — there should be at least one row with
# state=blocked + block_reason=kill_switch_off.
queue_json="$(run_host_agenttower agenttower queue --state blocked --json)"
if echo "$queue_json" | python3 -c "
import json, sys
rows = json.loads(sys.stdin.read())
match = [r for r in rows if r.get('block_reason') == 'kill_switch_off']
sys.exit(0 if match else 1)
" 2>/dev/null; then
  log "✅ E2E 3b: queue has blocked row with block_reason=kill_switch_off"
else
  fail "E2E 3b: no blocked kill_switch_off row found"
fi

# Re-enable for cleanliness.
log "routing enable (cleanup)"
run_host_agenttower agenttower routing enable >/dev/null

# ──────────────────────────────────────────────────────────────────────
# Pass
# ──────────────────────────────────────────────────────────────────────

log ""
log "🎉 FEAT-009 fresh-container E2E: ALL CHECKS PASSED"
log "  • Real tmux paste delivered body bytes to slave pane"
log "  • Real Docker bind-mount socket carried the daemon traffic"
log "  • Host routing toggle accepted; bench-container toggle refused"
log "  • Blocked-row body never reached the slave pane"
