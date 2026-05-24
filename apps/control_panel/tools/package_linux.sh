#!/usr/bin/env bash
# Linux packaging — AppImage primary + .deb secondary (T148, research R-13 + R-35)
#
# Status: STUB at T008 (Phase 1). Implementation lands in T148 (Phase 9 Polish).
#
# Prerequisites:
#   - Ubuntu 22.04+ build host (glibc 2.35+)
#   - Flutter ≥ 3.27 with Linux desktop enabled
#   - appimagetool (https://appimage.org/)
#   - dpkg-deb (built into Debian/Ubuntu)
#   - gpg for release-artifact signing
#
# Final implementation (T148) will:
#   1. flutter build linux --release
#   2. assemble AppDir from bundle/
#   3. appimagetool AppDir → AgentTower-Control-Panel-<version>-x86_64.AppImage
#   4. dpkg-deb --build → agenttower-control-panel_<version>_amd64.deb
#   5. gpg --detach-sign each artifact
#   6. emit build/linux/x64/release/AgentTower-Control-Panel-<version>.AppImage{,.asc}
#                build/linux/x64/release/agenttower-control-panel_<version>_amd64.deb{,.asc}
#
# This stub fails loudly so it isn't accidentally invoked before T148.

set -euo pipefail

echo "ERROR: T008 stub — Linux packaging not yet implemented." >&2
echo "       See T148 (Phase 9 Polish) in specs/012-flutter-control-panel/tasks.md." >&2
exit 1
