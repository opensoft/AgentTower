#!/usr/bin/env bash
# T172 — Bench-verified analyze regression gate (FEAT-012 Phase 9).
#
# Runs the four-step gate inside the flutter-bench Docker container (or any
# environment with Flutter 3.27.0 + Dart 3.6.0 + Python 3 on PATH):
#
#   1. flutter pub get
#   2. dart run build_runner build --delete-conflicting-outputs
#   3. flutter analyze --fatal-errors
#   4. flutter test test/core test/features
#
# Exits 0 only when ALL four steps pass; non-zero on any failure so CI /
# pre-merge hooks can use this as a single regression gate. Catches the
# language-API drift class of bug (e.g. the Riverpod 2.x vs 3.x
# `ref.mounted` mismatch fixed in commit 8e8e629) at PR time rather than
# at packaging (T148) or post-merge.
#
# Usage:
#   apps/control_panel/tools/bench_verify.sh
#
# Optional env vars:
#   FLUTTER          Path to the flutter binary (default: `flutter` on PATH).
#                    Set to /opt/flutter-3.27.0/bin/flutter inside the bench
#                    Docker image where the 3.27 pin lives.
#   SKIP_BUILD_RUNNER If non-empty, skip step 2. Useful when the freezed/
#                    json_serializable generated files are already up to
#                    date and you want a fast analyze-only smoke pass.
#
# Closes /speckit-analyze Round 5 T-N2.

set -euo pipefail

# ─── Locate the Flutter project root relative to this script. ──────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Sanity check: this script MUST run from inside apps/control_panel/.
if [[ ! -f "${PROJECT_DIR}/pubspec.yaml" ]]; then
    echo "ERROR: ${PROJECT_DIR}/pubspec.yaml not found." >&2
    echo "       bench_verify.sh expects to live at apps/control_panel/tools/." >&2
    exit 2
fi

cd "${PROJECT_DIR}"

FLUTTER_BIN="${FLUTTER:-flutter}"

# Pretty-print each step so a failure points at the right line in CI logs.
step() {
    printf '\n\033[1m── %s ──\033[0m\n' "$1"
}

# ─── Step 1: pub get ───────────────────────────────────────────────────
step "1/4  flutter pub get"
"${FLUTTER_BIN}" pub get

# ─── Step 2: build_runner (optional skip) ──────────────────────────────
if [[ -n "${SKIP_BUILD_RUNNER:-}" ]]; then
    step "2/4  build_runner SKIPPED (SKIP_BUILD_RUNNER set)"
else
    step "2/4  dart run build_runner build --delete-conflicting-outputs"
    "${FLUTTER_BIN}" pub run build_runner build --delete-conflicting-outputs
fi

# ─── Step 3: analyze ───────────────────────────────────────────────────
step "3/4  flutter analyze --fatal-errors"
"${FLUTTER_BIN}" analyze --fatal-errors

# ─── Step 4: test (test/core + test/features only — wide enough to ─────
#             catch regressions, narrow enough to stay fast).
step "4/4  flutter test test/core test/features"
"${FLUTTER_BIN}" test test/core test/features

printf '\n\033[1;32m✔ bench_verify: all 4 steps passed.\033[0m\n'
