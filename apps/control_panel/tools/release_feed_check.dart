// Standalone release-feed parser test (T036 + research R-12 + Round-3 R-42).
//
// Status: STUB at T008 (Phase 1). Implementation lands in T036 (Phase 2
// Foundational — update indicator + release-feed check).
//
// Purpose: lets us probe `https://releases.opensoft.one/agenttower/control-panel/latest.json`
// from CI / from a dev machine without running the full Flutter app. Useful for
// validating feed format changes before they break the in-app indicator.
//
// Final implementation (T036) will:
//   1. dart:io HttpClient GET to the feed URL
//   2. JSON-parse + schema-validate (research R-12)
//   3. compare against current version (CLI arg)
//   4. print: "current=<v> latest=<v> update_available=<bool>"
//
// This stub fails loudly so it isn't accidentally invoked before T036.

void main(List<String> args) {
  stderr.writeln('ERROR: T008 stub — release_feed_check not yet implemented.');
  stderr.writeln('       See T036 (Phase 2 Foundational) in specs/012-flutter-control-panel/tasks.md.');
  exitCode = 1;
}

// dart:io imports stubbed-out until T036 makes this runnable.
external dynamic get stderr;
external set exitCode(int value);
