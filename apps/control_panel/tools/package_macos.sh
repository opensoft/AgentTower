#!/usr/bin/env bash
# macOS packaging — .dmg + notarization + hardened runtime (T148, research R-13 + R-35)
#
# Status: STUB at T008 (Phase 1). Implementation lands in T148 (Phase 9 Polish).
#
# Prerequisites:
#   - macOS 13+ build host
#   - Flutter ≥ 3.27 with macOS desktop enabled
#   - Opensoft Apple Developer ID (reused from agenttowerd CA per R-35)
#   - create-dmg (brew install create-dmg)
#   - notarytool (Xcode 13+)
#
# Final implementation (T148) will:
#   1. flutter build macos --release
#   2. codesign --hardened-runtime
#   3. create-dmg the .app bundle
#   4. notarytool submit + wait + staple
#   5. emit build/macos/Build/Products/Release/AgentTower-Control-Panel-<version>.dmg
#
# This stub fails loudly so it isn't accidentally invoked before T148.

set -euo pipefail

echo "ERROR: T008 stub — macOS packaging not yet implemented." >&2
echo "       See T148 (Phase 9 Polish) in specs/012-flutter-control-panel/tasks.md." >&2
exit 1
