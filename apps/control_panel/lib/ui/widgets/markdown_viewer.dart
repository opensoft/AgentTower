import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import 'safe_url_launcher.dart';

/// Safe in-app markdown viewer per FR-079 + research R-09. T095 (Phase 4 US2).
///
/// **Safety subset (R-09 + FR-079)**: HTML inline is rejected
/// (`MarkdownStyleSheet.h1.fontFamily` etc. take precedence), and any
/// link URL whose scheme is `javascript:` or `data:` is dropped before
/// reaching `url_launcher`. Only `http(s):`, `mailto:`, and `file:`
/// schemes are passed through. The "Open externally" affordance
/// surfaces the same safety filter — the operator cannot bypass it
/// from the viewer chrome.
///
/// **No file I/O here**: the caller passes the rendered text. The
/// app never reads doc files itself per FR-001 + R-28; doc paths
/// resolve daemon-side and the daemon returns the content (or a
/// "Not found - see Drift" badge marker, which the caller renders
/// instead of this widget).
class MarkdownViewer extends StatelessWidget {
  const MarkdownViewer({
    super.key,
    required this.markdownText,
    this.sourceLabel,
    this.externalOpenUri,
  });

  /// The markdown body to render. Safe subset only; the widget does
  /// not strip HTML at parse time — callers MUST upstream-strip if
  /// they cannot guarantee the source.
  final String markdownText;

  /// Optional human-readable label of the source (e.g.
  /// "docs/product-requirements.md"). Rendered above the body.
  final String? sourceLabel;

  /// Optional URI the "Open externally" affordance should hand to
  /// `url_launcher`. The widget validates the scheme before launching.
  final Uri? externalOpenUri;

  // Swarm-review M-15: dropped `file:` from the in-viewer allowlist.
  // Daemon-supplied markdown bodies could otherwise embed
  // `[ssh key](file:///home/op/.ssh/id_rsa)` and the operator click
  // would open it. Filesystem URLs from daemon-resolved doc paths
  // (the legitimate use case) now route through SafeUrlLauncher's
  // file-confirmation modal, so the operator stays in the loop.
  static const Set<String> _allowedSchemes = {
    'http',
    'https',
    'mailto',
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (sourceLabel != null || externalOpenUri != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Row(
              children: [
                if (sourceLabel != null)
                  Expanded(
                    child: Text(
                      sourceLabel!,
                      style: theme.textTheme.labelSmall,
                      overflow: TextOverflow.ellipsis,
                    ),
                  )
                else
                  const Spacer(),
                if (externalOpenUri != null)
                  TextButton.icon(
                    onPressed: () => _openExternal(context, externalOpenUri!),
                    icon: const Icon(Icons.open_in_new, size: 16),
                    label: const Text('Open externally'),
                  ),
              ],
            ),
          ),
        Expanded(
          child: Markdown(
            data: markdownText,
            selectable: true,
            shrinkWrap: false,
            padding: const EdgeInsets.all(16),
            onTapLink: (text, href, title) => _onTapLink(context, href),
          ),
        ),
      ],
    );
  }

  static Future<void> _onTapLink(BuildContext context, String? href) async {
    if (href == null) return;
    final uri = Uri.tryParse(href);
    if (uri == null || !_allowedSchemes.contains(uri.scheme.toLowerCase())) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Link rejected — unsupported scheme: $href')),
      );
      return;
    }
    // Delegate to SafeUrlLauncher so the launch + error UX is unified
    // with the drift/current-work launch paths.
    await SafeUrlLauncher.openUri(context, uri);
  }

  static Future<void> _openExternal(BuildContext context, Uri uri) async {
    if (!_allowedSchemes.contains(uri.scheme.toLowerCase())) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Link rejected — unsupported scheme: $uri')),
      );
      return;
    }
    await SafeUrlLauncher.openUri(context, uri);
  }
}
