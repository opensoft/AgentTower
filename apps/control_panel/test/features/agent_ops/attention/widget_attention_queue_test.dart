import 'package:agenttower_control_panel/domain/models/attention_item.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart'
    hide ThemeMode;
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
import 'package:agenttower_control_panel/domain/severity.dart';
import 'package:agenttower_control_panel/features/agent_ops/attention/attention_queue_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/attention/providers.dart';
import 'package:agenttower_control_panel/features/shell/runtime_state_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Widget tests for [AttentionQueueView]. T150 (Phase 9 cross-cutting
/// widget tests).
///
/// Covers:
///   - icon + color + accessible-name for each severity tier
///     (info / warning / high / critical) per spec FR-052 + the
///     R-15 / R-22 redundancy triad surfaced via [SeverityVisuals]
///   - the empty-queue placeholder per spec FR-053 round-3
///     clarification ("no actionable items" branch).
///
/// The view is a `ConsumerStatefulWidget` that watches
/// [attentionListProvider] + [runtimeStateProvider]. We override both
/// at the test [ProviderScope] so the widget never touches the daemon
/// socket; this also lets us drive the loading → data transition
/// deterministically.
void main() {
  group('AttentionQueueView severity row visuals (FR-052 / R-22)', () {
    for (final tier in AttentionSeverity.values) {
      testWidgets('renders ${tier.wireValue} row with the matching icon, '
          'color, and accessible name', (tester) async {
        final item = _buildItem(severity: tier);
        await _pumpWithItems(tester, [item]);

        // Resolve the visuals the production widget itself would use.
        final theme = Theme.of(tester.element(find.byType(ListTile)));
        final expected = SeverityVisuals.forAttention(tier, theme.brightness);

        // Icon: a [CircleAvatar] wraps an [Icon] whose data is the
        // attention-class icon (Icons.block for blocked_queue_row).
        // The severity envelope drives the avatar background color, not
        // the icon itself, so the assertion below targets `CircleAvatar`.
        final avatar = tester.widget<CircleAvatar>(find.byType(CircleAvatar));
        expect(
          avatar.backgroundColor,
          expected.color,
          reason: 'avatar bg should match SeverityVisuals.color for '
              '${tier.wireValue}',
        );

        // Accessible name format matches `_AttentionRow.build`:
        //   "<semanticDescription> attention: <oneLineSummary>"
        // Assert against the Semantics WIDGET's configured label rather than
        // find.bySemanticsLabel: the merged semantics-tree node also absorbs
        // the ListTile title/subtitle, so an exact node-label match never
        // hits. The widget config is the load-bearing contract here.
        final expectedLabel =
            '${expected.semanticDescription} attention: ${item.oneLineSummary}';
        expect(
          find.byWidgetPredicate(
            (w) => w is Semantics && w.properties.label == expectedLabel,
          ),
          findsOneWidget,
          reason: 'semantic label should follow '
              '"<severityDesc> attention: <summary>" shape',
        );

        // R-22 redundancy: text label is part of the subtitle.
        expect(
          find.textContaining(expected.label),
          findsAtLeastNWidgets(1),
          reason: 'visible text label should be present (R-22)',
        );
      });
    }
  });

  group('AttentionQueueView empty-state (FR-053 round-3)', () {
    testWidgets('renders "no actionable attention items" placeholder when '
        'the queue is empty', (tester) async {
      await _pumpWithItems(tester, const []);

      // The production view delegates to [HealthyEmptyStateView] with
      // the copy "No actionable attention items." — see
      // `attention_queue_view.dart`. Round-3 clarification of FR-053
      // landed on this exact wording; if the copy changes update the
      // matcher in lockstep.
      expect(
        find.textContaining('No actionable attention items'),
        findsOneWidget,
      );
      expect(find.byType(ListTile), findsNothing);
    });
  });
}

Future<void> _pumpWithItems(
  WidgetTester tester,
  List<AttentionItem> items,
) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        // Force the runtime gate to its healthy path so the inner
        // `list.when(...)` actually renders (otherwise `RuntimeStateGate`
        // short-circuits with OutageStateView on the initial-unreachable
        // default).
        runtimeStateProvider.overrideWith(_FakeRuntimeStateNotifier.new),
        // Stub the attention list to the supplied items, regardless of
        // which (projectId, severity, attentionClass) tuple the view
        // requests.
        attentionListProvider.overrideWith((ref, _) async => items),
      ],
      // Not const: localizationsDelegates references static getters. The
      // view reads AppLocalizations.of(context) (T181 i18n sweep), which
      // throws a null-check error without these delegates wired.
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const AttentionQueueView(),
      ),
    ),
  );
  // Allow the FutureProvider to resolve and the stability controller
  // to publish the incoming list.
  await tester.pumpAndSettle();
}

AttentionItem _buildItem({
  required AttentionSeverity severity,
  String attentionId = 'att-1',
  AttentionClass attentionClass = AttentionClass.blockedQueueRow,
  String oneLineSummary = 'Queue row blocked awaiting approval',
}) {
  final now = DateTime.utc(2026, 1, 1, 12);
  return AttentionItem(
    attentionId: attentionId,
    attentionClass: attentionClass,
    severity: severity,
    ageStartedAt: now.subtract(const Duration(minutes: 5)),
    oneLineSummary: oneLineSummary,
    resolutionTarget: const ResolutionTarget.queueRow('msg-1'),
    asOf: now,
  );
}

/// Minimal Notifier that returns a healthy-populated runtime state so
/// the [RuntimeStateGate] short-circuit does not swallow our list.
class _FakeRuntimeStateNotifier extends RuntimeStateNotifier {
  @override
  RuntimeState build() => const RuntimeState(
        kind: RuntimeStateKind.runtimeHealthyPopulated,
      );
}
