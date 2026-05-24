# Windows packaging — MSIX bundle (T148, research R-13 + R-35)
#
# Status: STUB at T008 (Phase 1). Implementation lands in T148 (Phase 9 Polish).
#
# Prerequisites:
#   - Windows 10 1809+ build host
#   - Flutter >= 3.27 with Windows desktop enabled
#   - Opensoft code-signing certificate (reused from agenttowerd CA per R-35)
#   - msix Flutter package (declared in dev_dependencies when implementation lands)
#   - signtool.exe from Windows SDK
#
# Final implementation (T148) will:
#   1. flutter build windows --release
#   2. msix create with Opensoft cert
#   3. signtool verify of MSIX
#   4. emit build/windows/x64/runner/Release/control-panel.msix
#
# This stub fails loudly so it isn't accidentally invoked before T148.

Write-Error "T008 stub: Windows packaging not yet implemented. See T148 (Phase 9 Polish) in specs/012-flutter-control-panel/tasks.md."
exit 1
