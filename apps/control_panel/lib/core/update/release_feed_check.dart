import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Release-feed check + UpdateState provider. T036 + research R-12 + Round-3 R-42.
///
/// Fetches `https://releases.opensoft.one/agenttower/control-panel/latest.json`
/// once per app launch. On success, exposes whether an update is available
/// (i.e. feed-advertised version is greater than installed version).
/// On failure, stays silent (UpdateState.unknown). Per R-42, failure
/// outcome is surfaced via Settings → Doctor only.
///
/// The HTTPS GET is the ONLY outbound network call the app makes
/// (FR-001 + SC-009 exempt this code path per spec carve-out and
/// runtime verification via T155).
class ReleaseFeedChecker {
  ReleaseFeedChecker({
    Uri? feedUrl,
    Duration timeout = const Duration(seconds: 5),
  })  : feedUrl = feedUrl ??
            Uri.parse(
              'https://releases.opensoft.one/agenttower/control-panel/latest.json',
            ),
        _timeout = timeout;

  final Uri feedUrl;
  final Duration _timeout;

  /// Performs one HTTPS GET. Returns parsed feed on success, or null on any
  /// failure (network, TLS, parse, schema-mismatch). Per R-42, the failure is
  /// silent — caller surfaces it through the Settings → Doctor outcome row.
  Future<ReleaseFeed?> fetch() async {
    final client = HttpClient()..connectionTimeout = _timeout;
    try {
      final req = await client.getUrl(feedUrl);
      req.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final resp = await req.close().timeout(_timeout);
      if (resp.statusCode != 200) return null;
      final body = await resp.transform(utf8.decoder).join();
      final decoded = json.decode(body);
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

  factory ReleaseFeed.fromJson(Map<String, dynamic> json) => ReleaseFeed(
        version: json['version'] as String,
        channel: json['channel'] as String? ?? 'stable',
        releasedAt: DateTime.tryParse(json['released_at'] as String? ?? '')
                ?.toUtc() ??
            DateTime.fromMillisecondsSinceEpoch(0).toUtc(),
        releaseNotesUrl: json['release_notes_url'] as String? ?? '',
        minSupportedVersion: json['min_supported_version'] as String? ?? '0.0.0',
      );

  final String version;
  final String channel;
  final DateTime releasedAt;
  final String releaseNotesUrl;
  final String minSupportedVersion;
}

/// Update state exposed to UI.
enum UpdateState {
  unknown, // pre-check OR fetch failed
  upToDate,
  updateAvailable,
}

class UpdateInfo {
  const UpdateInfo({
    required this.state,
    required this.installedVersion,
    this.feed,
    this.lastCheckedAt,
  });
  final UpdateState state;
  final String installedVersion;
  final ReleaseFeed? feed;
  final DateTime? lastCheckedAt;
}

/// Provider — call `ref.read(updateInfoProvider.notifier).runOnce()` from
/// `main.dart` after bootstrap to fire the FR-068 one-per-launch check.
class UpdateInfoNotifier extends Notifier<UpdateInfo> {
  UpdateInfoNotifier({required this.installedVersion, ReleaseFeedChecker? checker})
      : _checker = checker ?? ReleaseFeedChecker();

  final String installedVersion;
  final ReleaseFeedChecker _checker;
  bool _hasRun = false;

  @override
  UpdateInfo build() => UpdateInfo(
        state: UpdateState.unknown,
        installedVersion: installedVersion,
      );

  /// Idempotent — calling more than once per process lifetime is a no-op
  /// per FR-068 "at most once per app launch".
  Future<void> runOnce() async {
    if (_hasRun) return;
    _hasRun = true;
    final feed = await _checker.fetch();
    final now = DateTime.now().toUtc();
    if (feed == null) {
      state = UpdateInfo(
        state: UpdateState.unknown,
        installedVersion: installedVersion,
        lastCheckedAt: now,
      );
      return;
    }
    final available = _isNewer(feed.version, installedVersion);
    state = UpdateInfo(
      state: available ? UpdateState.updateAvailable : UpdateState.upToDate,
      installedVersion: installedVersion,
      feed: feed,
      lastCheckedAt: now,
    );
  }

  /// Naive semver-ish comparison: "1.2.3" > "1.2.2".
  static bool _isNewer(String advertised, String installed) {
    final a = advertised.split('.').map(int.tryParse).toList();
    final b = installed.split('.').map(int.tryParse).toList();
    for (var i = 0; i < a.length && i < b.length; i++) {
      final av = a[i] ?? 0;
      final bv = b[i] ?? 0;
      if (av > bv) return true;
      if (av < bv) return false;
    }
    return a.length > b.length;
  }
}
