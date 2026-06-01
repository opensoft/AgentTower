import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Release-feed check. T036 + research R-12 + Round-3 R-42.
///
/// Fetches `https://releases.opensoft.one/agenttower/control-panel/latest.json`
/// once per app launch. On success, returns the parsed feed so the caller
/// can compare the advertised version against the installed version.
/// On failure, stays silent (returns null). Per R-42, the failure
/// outcome is surfaced via Settings → Doctor only.
///
/// The HTTPS GET is the ONLY outbound network call the app makes
/// (FR-001 + SC-009 exempt this code path per spec carve-out and
/// runtime verification via T155).
class ReleaseFeedChecker {
  ReleaseFeedChecker({
    Uri? feedUrl,
    Duration timeout = const Duration(seconds: 5),
    String userAgent = 'AgentTower-ControlPanel/0.1 (+https://opensoft.one)',
  })  : feedUrl = feedUrl ??
            Uri.parse(
              'https://releases.opensoft.one/agenttower/control-panel/latest.json',
            ),
        _timeout = timeout,
        _userAgent = userAgent {
    // FR-001 + SC-009 carve-out: only this exact code path performs
    // outbound HTTPS. Enforce HTTPS scheme up-front so a misconfigured
    // override (env var, test, future Settings field) cannot downgrade
    // the connection to plain HTTP.
    if (this.feedUrl.scheme != 'https') {
      throw ArgumentError.value(
        this.feedUrl,
        'feedUrl',
        'Release feed URL must use https scheme',
      );
    }
  }

  final Uri feedUrl;
  final Duration _timeout;
  final String _userAgent;

  /// Performs one HTTPS GET. Returns parsed feed on success, or null on any
  /// failure (network, TLS, parse, schema-mismatch). Per R-42, the failure is
  /// silent — caller surfaces it through the Settings → Doctor outcome row.
  Future<ReleaseFeed?> fetch() async {
    final client = HttpClient()..connectionTimeout = _timeout;
    try {
      final req = await client.getUrl(feedUrl);
      // Lock down the request: no redirect-chasing (a redirect to http://
      // would be a downgrade vector), tight User-Agent for log/abuse
      // attribution, Accept gated to JSON.
      req.followRedirects = false;
      req.headers.set(HttpHeaders.acceptHeader, 'application/json');
      req.headers.set(HttpHeaders.userAgentHeader, _userAgent);
      final resp = await req.close().timeout(_timeout);
      if (resp.statusCode != 200) return null;
      // Bound the untrusted read: a valid latest.json is < ~4 KB. Reject an
      // oversized payload (declared or streamed) to avoid a client-side OOM
      // on this defensive, untrusted-input path.
      const maxBytes = 64 * 1024;
      if (resp.contentLength > maxBytes) return null;
      final builder = BytesBuilder(copy: false);
      var total = 0;
      await for (final chunk in resp) {
        total += chunk.length;
        if (total > maxBytes) return null;
        builder.add(chunk);
      }
      final body = utf8.decode(builder.takeBytes());
      final Object? decoded = json.decode(body);
      if (decoded is! Map<String, dynamic>) return null;
      return ReleaseFeed.fromJson(decoded);
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }
}

/// Schema per research R-12.
class ReleaseFeed {
  const ReleaseFeed({
    required this.version,
    required this.channel,
    required this.releasedAt,
    required this.releaseNotesUrl,
    required this.minSupportedVersion,
  });

  factory ReleaseFeed.fromJson(Map<String, dynamic> json) {
    final version = json['version'];
    if (version is! String || !_isLikelyVersion(version)) {
      throw const FormatException('Release feed missing or malformed `version`');
    }
    final minSupported = json['min_supported_version'];
    if (minSupported != null && minSupported is! String) {
      throw const FormatException(
        'Release feed `min_supported_version` must be a string',
      );
    }
    return ReleaseFeed(
      version: version,
      channel: json['channel'] as String? ?? 'stable',
      releasedAt:
          DateTime.tryParse(json['released_at'] as String? ?? '')?.toUtc() ??
              DateTime.fromMillisecondsSinceEpoch(0).toUtc(),
      releaseNotesUrl: json['release_notes_url'] as String? ?? '',
      minSupportedVersion: (minSupported as String?) ?? '0.0.0',
    );
  }

  /// Best-effort sanity check on a version string ("MAJOR.MINOR" or
  /// "MAJOR.MINOR.PATCH(-suffix)?"). We don't pull in a full semver parser
  /// for the MVP — the goal is to reject obviously garbage payloads.
  static bool _isLikelyVersion(String v) =>
      RegExp(r'^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?$').hasMatch(v);

  final String version;
  final String channel;
  final DateTime releasedAt;
  final String releaseNotesUrl;
  final String minSupportedVersion;
}

/// Provider for the installed app version. Override in `main.dart` from
/// `package_info_plus`'s `PackageInfo.version`. Defaults to `'0.0.0-dev'`
/// for widget tests.
final installedAppVersionProvider =
    Provider<String>((ref) => '0.0.0-dev');

/// Provider for the [ReleaseFeedChecker] instance — the documented
/// test-override seam. Consumed by `releaseFeedCheckProvider` in
/// `lib/features/shell/version_display.dart`, which is the live FR-068
/// one-per-launch path (its cached `FutureProvider` result is shared by
/// the Dashboard badge and the Settings tile). Test overrides supply a
/// stub checker so the network is never hit in unit/widget tests.
final releaseFeedCheckerProvider =
    Provider<ReleaseFeedChecker>((ref) => ReleaseFeedChecker());

// NOTE: an earlier `UpdateInfoNotifier` / `updateInfoProvider` cluster was
// intended as a shared "single source of truth" for update state but was
// never wired into `main.dart` or any widget — its `runOnce()` was never
// called, so it sat at `UpdateState.unknown` forever. It (and the
// `UpdateInfo`/`UpdateState` types + `_isNewer` comparator it owned) has
// been removed so the live `releaseFeedCheckProvider` path is the only
// FR-068 path, rather than leaving dead code behind a misleading
// "single source of truth" docstring.
