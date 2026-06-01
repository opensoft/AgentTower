import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/l10n/app_localizations.dart';

/// FR-079 / FR-001 / Swarm-review H-D1/H-D2/H-D3 / M-15 — single
/// safe gateway for every `launchUrl` call across Phase 4-6.
///
/// **Why centralize**: prior code launched daemon-supplied URLs
/// (drift evidence url + file pointer, current-work doc paths,
/// markdown link clicks) via `launchUrl` with no scheme check or with
/// inconsistent allowlists. A malicious or buggy daemon response
/// could embed `javascript:`, `data:`, `vbscript:`, or
/// `file:///etc/shadow` and the OS would open it.
///
/// **Policy**:
///   - HTTP/HTTPS/mailto: launched directly.
///   - file: launched only after an operator confirmation modal
///     showing the full path. `Uri.file()` is path-traversal-safe
///     for the path encoding itself, but the daemon's authority to
///     produce arbitrary paths is unbounded — the modal keeps the
///     operator in the loop.
///   - Everything else (javascript:, data:, vbscript:, about:, etc.):
///     rejected with a SnackBar naming the scheme.
class SafeUrlLauncher {
  const SafeUrlLauncher._();

  /// Schemes that launch directly with no confirmation.
  static const Set<String> _autoLaunchSchemes = {
    'http',
    'https',
    'mailto',
  };

  /// Schemes that launch only after operator confirmation.
  static const Set<String> _confirmSchemes = {'file'};

  /// Parses [href] and launches according to the policy above.
  /// Returns `true` if a launch was attempted (regardless of OS
  /// success), `false` if the scheme was rejected or the user
  /// cancelled the confirmation modal.
  static Future<bool> open(BuildContext context, String href) async {
    final uri = Uri.tryParse(href);
    if (uri == null || uri.scheme.isEmpty) {
      _reject(context, href, 'malformed URI');
      return false;
    }
    return openUri(context, uri);
  }

  /// As [open] but takes a pre-parsed [Uri].
  static Future<bool> openUri(BuildContext context, Uri uri) async {
    final scheme = uri.scheme.toLowerCase();
    if (_autoLaunchSchemes.contains(scheme)) {
      return _doLaunch(context, uri);
    }
    if (_confirmSchemes.contains(scheme)) {
      final confirmed = await _confirmFileLaunch(context, uri);
      if (confirmed != true) return false;
      return _doLaunch(context, uri);
    }
    _reject(context, uri.toString(), 'unsupported scheme `$scheme`');
    return false;
  }

  /// Convenience for "this is definitely a filesystem path the
  /// daemon resolved" callers. Wraps the path in `Uri.file` so
  /// query/fragment characters are escaped safely, then routes
  /// through the confirmation path.
  static Future<bool> openFile(BuildContext context, String path) =>
      openUri(context, Uri.file(path));

  static Future<bool> _doLaunch(BuildContext context, Uri uri) async {
    final l10n = AppLocalizations.of(context);
    bool ok;
    try {
      ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      ok = false;
    }
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.safeUrlOsCouldNotOpen(_summarize(uri)))),
      );
    }
    return true;
  }

  static Future<bool?> _confirmFileLaunch(BuildContext context, Uri uri) {
    final l10n = AppLocalizations.of(context);
    return showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(l10n.safeUrlConfirmTitle),
        content: SizedBox(
          width: 460,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(l10n.safeUrlConfirmBody),
              const SizedBox(height: 12),
              SelectableText(
                uri.toFilePath(),
                style: const TextStyle(fontFamily: 'monospace'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.safeUrlCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(l10n.safeUrlOpenExternally),
          ),
        ],
      ),
    );
  }

  static void _reject(BuildContext context, String href, String why) {
    if (!context.mounted) return;
    final l10n = AppLocalizations.of(context);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(l10n.safeUrlLinkRejected(why, _summarize(href))),
      ),
    );
  }

  static String _summarize(Object href) {
    final s = href.toString();
    return s.length <= 80 ? s : '${s.substring(0, 77)}…';
  }
}
