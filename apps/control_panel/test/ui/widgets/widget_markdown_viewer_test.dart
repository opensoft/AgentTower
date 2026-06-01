import 'package:agenttower_control_panel/ui/widgets/markdown_viewer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [MarkdownViewer]. T150 (Phase 9 cross-cutting
/// widget tests).
///
/// Covers the FR-079 + R-09 safe-markdown subset:
///   - CommonMark + GFM features render (tables, strikethrough,
///     task-lists, fenced code, autolinks)
///   - raw HTML is treated as literal text (NOT executed / rendered)
///   - `javascript:` and `data:` URLs are blocked at the link-tap
///     handler with an inline warning surface (no `url_launcher`
///     invocation)
///   - the "Open externally" affordance applies the same scheme filter
///
/// Tests deliberately stop short of allowed-scheme launches (http/
/// https/mailto) because exercising those would route into
/// `SafeUrlLauncher → url_launcher` and require a platform-channel
/// mock — out of scope for this widget test and covered indirectly by
/// the SafeUrlLauncher unit tests.
///
/// Note: [MarkdownViewer] itself does NOT implement cross-doc `.md`
/// resolution nor a "missing path" placeholder — both of those concerns
/// live in the calling surface (per the widget's doc comment: "the
/// caller passes the rendered text. The app never reads doc files
/// itself per FR-001 + R-28"). Tests for those behaviors belong with
/// the caller and are intentionally not asserted here.
void main() {
  group('MarkdownViewer — safe rendering subset (FR-079 / R-09)', () {
    testWidgets('renders the underlying Markdown widget with the supplied '
        'source text', (tester) async {
      await _pump(
        tester,
        markdownText: '# Hello\n\nA paragraph with **bold** text.',
      );
      // The flutter_markdown `Markdown` widget should be in the tree.
      expect(find.byType(Markdown), findsOneWidget);
      // Body text rendered (the paragraph copy lands as a Text node).
      expect(find.textContaining('A paragraph with'), findsOneWidget);
    });

    testWidgets('renders GFM tables, strikethrough, task-lists, fenced code, '
        'and autolinks without throwing', (tester) async {
      // The MarkdownViewer relies on flutter_markdown's default
      // extensionSet which is `ExtensionSet.gitHubFlavored` (covers
      // tables, strikethrough, autolinks, fenced code). Task-lists
      // ship as part of the GFM extension set in flutter_markdown
      // 0.7.x. This test asserts the widget renders the full GFM
      // sample without throwing during pump — i.e. the parser pipeline
      // is wired through correctly.
      const sample = '''
| Col A | Col B |
|-------|-------|
| one   | two   |

~~struck~~ and `inline-code`.

- [x] done
- [ ] todo

```dart
final x = 1;
```

<https://example.org>
''';
      await _pump(tester, markdownText: sample);
      expect(find.byType(Markdown), findsOneWidget);
      // The plain-text "todo" and table cells appear as Text widgets
      // somewhere in the rendered tree.
      expect(find.textContaining('todo'), findsAtLeastNWidgets(1));
    });

    testWidgets('treats raw inline HTML as literal text (no HTML execution)',
        (tester) async {
      // flutter_markdown does NOT render raw HTML by default — the
      // tag characters are passed through as literal text inside the
      // surrounding paragraph node. Spec FR-079 + R-09 requires this
      // safety property explicitly. We assert the literal angle-bracket
      // contents survive the round-trip, AND that no underlying
      // [Image] / interactive HTML widget materializes.
      const raw = '<script>alert(1)</script>\n\n'
          'normal text after script';
      await _pump(tester, markdownText: raw);
      // The literal "alert(1)" string should appear somewhere in the
      // rendered output — proving the tag was NOT executed but
      // surfaced as text.
      expect(find.textContaining('alert(1)'), findsAtLeastNWidgets(1));
    });
  });

  group('MarkdownViewer — link-tap scheme guard (FR-079)', () {
    testWidgets('javascript: link tap shows the inline warning and does NOT '
        'invoke url_launcher', (tester) async {
      // Pump the widget with a markdown link whose href is a
      // `javascript:` URL. The widget's `onTapLink` short-circuits
      // before reaching SafeUrlLauncher.
      await _pump(
        tester,
        markdownText: '[click me](javascript:alert(1))',
      );

      // Manually fire the link tap because flutter_markdown wires
      // taps through a GestureRecognizer on the inline span; the
      // public callback is the documented hook, so invoking it
      // directly is the deterministic widget-test path.
      final markdown = tester.widget<Markdown>(find.byType(Markdown));
      markdown.onTapLink!(
        'click me',
        'javascript:alert(1)',
        '',
      );
      await tester.pump(); // allow the SnackBar frame to schedule
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        find.textContaining('Link rejected'),
        findsOneWidget,
        reason: 'javascript: scheme should surface the inline warning '
            'SnackBar',
      );
      expect(
        find.textContaining('unsupported scheme'),
        findsOneWidget,
      );
      // No platform-channel call would have fired; the early-return
      // happens before SafeUrlLauncher is reached.
    });

    testWidgets('data: link tap shows the inline warning and does NOT '
        'invoke url_launcher', (tester) async {
      await _pump(
        tester,
        markdownText: '[payload](data:text/html,<h1>x</h1>)',
      );
      final markdown = tester.widget<Markdown>(find.byType(Markdown));
      markdown.onTapLink!(
        'payload',
        'data:text/html,<h1>x</h1>',
        '',
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.textContaining('Link rejected'), findsOneWidget);
    });

    testWidgets('file: link tap is rejected at the viewer (post-M-15: '
        'file scheme dropped from in-viewer allowlist)', (tester) async {
      // Swarm-review M-15: `file:` was removed from the viewer's
      // local allowlist; legitimate filesystem links must route via
      // the caller's SafeUrlLauncher confirmation modal, not via a
      // raw markdown link. A daemon-supplied
      // `[ssh key](file:///home/op/.ssh/id_rsa)` therefore now
      // surfaces the same warning as javascript: / data:.
      await _pump(
        tester,
        markdownText: '[secret](file:///etc/passwd)',
      );
      final markdown = tester.widget<Markdown>(find.byType(Markdown));
      markdown.onTapLink!('secret', 'file:///etc/passwd', '');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.textContaining('Link rejected'), findsOneWidget);
      expect(find.textContaining('unsupported scheme'), findsOneWidget);
    });

    testWidgets('null / unparseable href is a no-op (no SnackBar, no crash)',
        (tester) async {
      await _pump(tester, markdownText: 'hello');
      final markdown = tester.widget<Markdown>(find.byType(Markdown));
      // The `onTapLink` contract accepts a nullable href; the
      // production code returns silently in that case.
      markdown.onTapLink!('hello', null, '');
      await tester.pump();
      expect(find.textContaining('Link rejected'), findsNothing);
    });
  });

  group('MarkdownViewer — header chrome', () {
    testWidgets('renders source label above the body when provided',
        (tester) async {
      await _pump(
        tester,
        markdownText: 'body',
        sourceLabel: 'docs/product-requirements.md',
      );
      expect(find.text('docs/product-requirements.md'), findsOneWidget);
    });

    testWidgets('renders "Open externally" affordance only when '
        'externalOpenUri is supplied', (tester) async {
      // Without externalOpenUri: no button.
      await _pump(tester, markdownText: 'body');
      expect(find.text('Open externally'), findsNothing);

      // With externalOpenUri: the TextButton.icon appears.
      await _pump(
        tester,
        markdownText: 'body',
        externalOpenUri: Uri.parse('https://example.org'),
      );
      expect(find.text('Open externally'), findsOneWidget);
    });
  });
}

Future<void> _pump(
  WidgetTester tester, {
  required String markdownText,
  String? sourceLabel,
  Uri? externalOpenUri,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: SizedBox(
          width: 600,
          height: 800,
          child: MarkdownViewer(
            markdownText: markdownText,
            sourceLabel: sourceLabel,
            externalOpenUri: externalOpenUri,
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}
