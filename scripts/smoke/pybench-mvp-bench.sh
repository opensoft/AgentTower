#!/usr/bin/env bash
set -euo pipefail

# Start a disposable py-bench container shaped like an AgentTower MVP bench.
#
# This is preparation for docs/mvp-test-plans.md Plan 2 and Plan 3. It keeps
# AgentTower state isolated on the host, starts the host daemon, then launches a
# bench container with:
#
# - py-bench:brett as the default image
# - UID 1000 bench user
# - the repo mounted at /workspace
# - the host daemon socket mounted at /run/agenttower/agenttowerd.sock
# - the host AgentTower state directory mounted at the same bench-user path so
#   tmux pipe-pane logs are host-visible
# - a tmux session with master-a, master-b, slave-1, and swarm-1 windows

usage() {
  cat <<'USAGE'
Usage:
  scripts/smoke/pybench-mvp-bench.sh up
  scripts/smoke/pybench-mvp-bench.sh status
  scripts/smoke/pybench-mvp-bench.sh shell
  scripts/smoke/pybench-mvp-bench.sh down
  scripts/smoke/pybench-mvp-bench.sh reset

Environment overrides:
  AGENTTOWER_SMOKE_IMAGE      Docker image, default py-bench:brett
  AGENTTOWER_SMOKE_NAME       Container name, default agenttower-py-bench-smoke
  AGENTTOWER_SMOKE_ROOT       Host state root, default ./.tmp/agenttower-smoke
  AGENTTOWER_SMOKE_SESSION    tmux session name, default agenttower-smoke
USAGE
}

cmd="${1:-}"
case "$cmd" in
  up|status|shell|down|reset|-h|--help) ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$cmd" == "-h" || "$cmd" == "--help" ]]; then
  usage
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${AGENTTOWER_SMOKE_IMAGE:-py-bench:brett}"
name="${AGENTTOWER_SMOKE_NAME:-agenttower-py-bench-smoke}"
session="${AGENTTOWER_SMOKE_SESSION:-agenttower-smoke}"
smoke_root="${AGENTTOWER_SMOKE_ROOT:-$repo_root/.tmp/agenttower-smoke}"

host_home="$smoke_root/home"
xdg_config="$smoke_root/xdg/config"
xdg_state="$smoke_root/xdg/state"
xdg_cache="$smoke_root/xdg/cache"
host_state_dir="$xdg_state/opensoft/agenttower"
host_socket="$host_state_dir/agenttowerd.sock"
host_logs="$host_state_dir/logs"
host_venv="$smoke_root/venv"

container_home="/home/brett"
container_state_dir="$container_home/.local/state/opensoft/agenttower"
container_socket_default="/run/agenttower/agenttowerd.sock"
container_venv="/tmp/agenttower-venv"
container_path="$container_venv/bin:/home/brett/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

if command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
elif command -v python >/dev/null 2>&1; then
  python_bin="python"
else
  echo "error: neither python3 nor python is available on the host PATH" >&2
  exit 1
fi

run_host_agenttower() {
  HOME="$host_home" \
  XDG_CONFIG_HOME="$xdg_config" \
  XDG_STATE_HOME="$xdg_state" \
  XDG_CACHE_HOME="$xdg_cache" \
  PATH="$host_venv/bin:$PATH" \
  "$@"
}

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "$name"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "$name"
}

ensure_host_daemon() {
  mkdir -p "$host_home" "$xdg_config" "$xdg_state" "$xdg_cache"
  if [[ ! -x "$host_venv/bin/python" ]]; then
    "$python_bin" -m venv "$host_venv"
  fi
  "$host_venv/bin/python" -m pip install -e '.[test]' >/dev/null
  run_host_agenttower agenttower config init >/dev/null
  cat >"$xdg_config/opensoft/agenttower/config.toml" <<EOF
# AgentTower smoke-test config.

[containers]
name_contains = ["$name"]
scan_interval_seconds = 5
EOF
  run_host_agenttower agenttower ensure-daemon >/dev/null
  if [[ ! -S "$host_socket" ]]; then
    echo "error: host daemon socket was not created: $host_socket" >&2
    exit 1
  fi
  mkdir -p "$host_logs"
}

start_container() {
  if container_running; then
    echo "bench already running: $name"
    return 0
  fi

  if container_exists; then
    docker rm "$name" >/dev/null
  fi

  docker run -d \
    --name "$name" \
    --label opensoft.bench=true \
    --label agenttower.smoke=true \
    -e AGENTTOWER_SOCKET="$container_socket_default" \
    -e XDG_STATE_HOME="$container_home/.local/state" \
    -e XDG_CONFIG_HOME="$container_home/.config" \
    -e XDG_CACHE_HOME="$container_home/.cache" \
    -e PATH="$container_path" \
    -v "$repo_root:/workspace" \
    -v "$host_state_dir:$container_state_dir" \
    -v "$host_socket:$container_socket_default" \
    -w /workspace \
    "$image" \
    sleep infinity >/dev/null

  docker exec "$name" sh -lc "python3 -m venv '$container_venv' && '$container_venv/bin/python' -m pip install -e '.[test]' >/dev/null"
}

start_tmux_layout() {
  docker exec "$name" sh -lc "tmux has-session -t '$session' 2>/dev/null || tmux new-session -d -s '$session' -n master-a 'bash --noprofile --norc'"
  docker exec "$name" sh -lc "tmux list-windows -t '$session' -F '#{window_name}' | grep -Fxq master-b || tmux new-window -t '$session' -n master-b 'bash --noprofile --norc'"
  docker exec "$name" sh -lc "tmux list-windows -t '$session' -F '#{window_name}' | grep -Fxq slave-1 || tmux new-window -t '$session' -n slave-1 'bash --noprofile --norc'"
  docker exec "$name" sh -lc "tmux list-windows -t '$session' -F '#{window_name}' | grep -Fxq swarm-1 || tmux new-window -t '$session' -n swarm-1 'bash --noprofile --norc'"
}

print_status() {
  echo "image=$image"
  echo "container=$name"
  echo "session=$session"
  echo "host_home=$host_home"
  echo "xdg_config=$xdg_config"
  echo "xdg_state=$xdg_state"
  echo "xdg_cache=$xdg_cache"
  echo "host_socket=$host_socket"
  echo "host_logs=$host_logs"
  if container_running; then
    echo "container_status=running"
    docker exec "$name" sh -lc "PATH='$container_path' agenttower status >/dev/null && echo container_agenttower_status=ok || echo container_agenttower_status=failed"
    docker exec "$name" sh -lc "tmux list-windows -t '$session' -F 'tmux_window=#{window_index}:#{window_name}' 2>/dev/null || true"
  else
    echo "container_status=stopped"
  fi
}

case "$cmd" in
  up)
    ensure_host_daemon
    start_container
    start_tmux_layout
    run_host_agenttower agenttower scan --containers --panes >/dev/null || true
    print_status
    ;;
  status)
    print_status
    ;;
  shell)
    if ! container_running; then
      echo "error: bench is not running; run: $0 up" >&2
      exit 1
    fi
    docker exec -it "$name" zsh
    ;;
  down)
    if container_exists; then
      docker rm -f "$name" >/dev/null
    fi
    if [[ -S "$host_socket" ]]; then
      run_host_agenttower agenttower stop-daemon >/dev/null || true
    fi
    echo "stopped bench and daemon for $name"
    ;;
  reset)
    if container_exists; then
      docker rm -f "$name" >/dev/null
    fi
    if [[ -S "$host_socket" ]]; then
      run_host_agenttower agenttower stop-daemon >/dev/null || true
    fi
    rm -rf "$smoke_root"
    echo "removed bench, daemon, and smoke state for $name"
    ;;
esac
