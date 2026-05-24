# `lib/ui/widgets/` — cross-cutting widget catalog

These helpers are load-bearing for every Phase 4-8 feature surface and
should be reused by Phase 9 + future-feature work. Each was introduced
by the 2026-05-24 swarm review to close a systemic finding; the source
report is at `specs/012-flutter-control-panel/swarm-review-2026-05-24.md`.

## RuntimeStateGate + state views (`runtime_state_views.dart`)

**Closes:** CR-6 (FR-004 five-state coverage).
**Use when:** rendering any live-data surface backed by a Riverpod
`FutureProvider` reading from the daemon.

```dart
final list = ref.watch(myListProvider);
return RuntimeStateGate(
  onUnreachable: (s) => OutageStateView(state: s, surfaceLabel: 'Foo',
    onRetry: () => ref.invalidate(myListProvider)),
  onIncompatible: (s) => ContractIncompatStateView(state: s, surfaceLabel: 'Foo'),
  child: list.when(
    data: (rows) => rows.isEmpty
        ? HealthyEmptyStateView(message: 'No foos.')
        : MyRealList(rows),
    loading: () => const LoadingStateView(),
    error: (e, _) => ErrorStateView(error: e, surfaceLabel: 'foo',
      onRetry: () => ref.invalidate(myListProvider)),
  ),
);
```

**Don't:** render raw `Center(Text('Failed: $err'))` strings — that
conflates daemon-down with query-rejected, which FR-004 forbids.

## ContractCheckedButton (`contract_checked_button.dart`)

**Closes:** CR-7 (FR-002 mutation-disable invariant).
**Use when:** building any button that performs a mutation (calls
`AppClient.*` with an `idempotency_key`).

```dart
ContractCheckedButton(
  additionalGate: !_submitting,           // optional extra predicate
  onPressed: () => _doSubmit(),
  builder: (ctx, onPressed, reason) => FilledButton.icon(
    onPressed: onPressed,                  // null when gated; renders disabled
    icon: const Icon(Icons.send),
    label: Text(reason ?? 'Submit'),       // tooltip is auto-applied by gate
  ),
);
```

The gate disables the action with an FR-002-required inline tooltip
naming the missing contract version when the runtime is
`contractVersionIncompatible` or `runtimeUnreachable`. **Don't** hide
the button — spec is explicit that operators must see the action
exists but is unavailable.

## SafeUrlLauncher (`safe_url_launcher.dart`)

**Closes:** H-D1, H-D2, H-D3, M-15 (FR-079 scheme allowlist + FR-001
daemon-supplied path containment).
**Use when:** opening any URL or filesystem path supplied by the
daemon (drift evidence URLs, doc paths, markdown link clicks).

```dart
// String href from a markdown body / daemon row:
await SafeUrlLauncher.open(context, href);

// Pre-parsed Uri:
await SafeUrlLauncher.openUri(context, uri);

// "I know this is a filesystem path":
await SafeUrlLauncher.openFile(context, '/path/from/daemon');
```

Policy: http/https/mailto launch directly; file: requires operator
confirmation (modal showing the full path); everything else is
rejected with a SnackBar. **Don't** call `launchUrl(Uri.parse(href))`
directly — the daemon's authority to produce arbitrary URLs is
unbounded.

## SeverityVisuals (`../../domain/severity.dart`)

**Closes:** CR-8 + H-C3 (R-15 palette + R-22 icon/text/color
redundancy triad).
**Use when:** rendering any severity badge for `DriftSeverity` /
`AttentionSeverity` / `NotificationSeverity`.

```dart
final sev = SeverityVisuals.forDrift(drift.severity, theme.brightness);
// sev.color, sev.onColor, sev.icon, sev.label, sev.semanticDescription
CircleAvatar(backgroundColor: sev.color,
  child: Icon(sev.icon, color: sev.onColor));
Text('${sev.label} · ${drift.summary}');           // R-22 text label
Semantics(label: '${sev.semanticDescription} ...'); // screen-reader path
```

**Don't** map severities to `Theme.colorScheme.error/tertiary/...`
directly — those Material slots aren't tuned for R-15 contrast and
break R-22 redundancy.

## withAsOfDefault (`../../core/json_utils.dart`)

**Closes:** H-G3 (duplicated `_withAsOf` across 4 provider files
with divergent behavior).
**Use when:** mapping daemon-row maps into freezed models in a
provider.

```dart
final asOf = DateTime.now().toUtc();
return page.items
    .map((m) => MyModel.fromJson(withAsOfDefault(m, asOf)))
    .toList(growable: false);
```

Daemon contract is snake_case-only; the helper only checks `as_of`.

## MasterClassCapabilities envelope (`../../domain/master_qualification.dart`)

**Closes:** H-G1 (FR-071 enforcement) + H-G2 (degraded surface).
**Use when:** constructing a `MasterSummary` or checking master
qualification.

```dart
// Construction:
MasterSummary.tryFromAgent(...);     // returns null if FR-071 not met

// Qualification check + degraded surfacing:
final env = await ref.read(masterClassCapabilitiesProvider.future);
if (env.degraded) {
  // Render the operator banner naming env.degradedReason.
}
final ok = qualifiesAsMasterEnvelope(agent, env);
```

**Don't** call the raw freezed `MasterSummary(...)` factory from an
`AdoptedAgent`-derived shape — FR-071 invariant is unenforced.

## @JsonEnum convention (`lib/domain/models/common_enums.dart` + supporting files)

**Closes:** CR-1 (every multi-word enum's `fromJson` threw without it).
**Use when:** adding any new enum that crosses the daemon wire.

```dart
@JsonEnum(valueField: 'wireValue')
enum MyKind {
  fooBar('foo_bar'),
  bazQux('baz_qux');
  const MyKind(this.wireValue);
  final String wireValue;
}
```

Codegen will then emit the snake_case wire string. **Don't** ship a
multi-word enum without the annotation — the integration tests will
catch it but you'll waste a round-trip.

---

## Patterns recap

| New code does … | Use … |
|---|---|
| renders a daemon-backed list/detail | `RuntimeStateGate` + matching `*StateView` |
| has a mutation button (Submit/Add/Cancel/Trigger/Acknowledge) | `ContractCheckedButton` |
| opens a daemon-supplied URL or file path | `SafeUrlLauncher` |
| renders a severity badge | `SeverityVisuals` |
| maps daemon rows to a freezed model | `withAsOfDefault` |
| checks master qualification or constructs a MasterSummary | `MasterSummary.tryFromAgent` + `MasterClassCapabilities` envelope |
| adds a new enum that crosses the wire | `@JsonEnum(valueField: 'wireValue')` |
