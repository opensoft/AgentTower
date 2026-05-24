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
      final body = await resp.transform(utf8.decoder).join();
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

/// Provider for the installed app version. Override in `main.dart` from
/// `package_info_plus`'s `PackageInfo.version`. Defaults to `'0.0.0-dev'`
/// for widget tests.
final installedAppVersionProvider =
    Provider<String>((ref) => '0.0.0-dev');

/// Provider for the [ReleaseFeedChecker] instance. Test overrides supply
/// a stub checker so the network is never hit in unit/widget tests.
final releaseFeedCheckerProvider =
    Provider<ReleaseFeedChecker>((ref) => ReleaseFeedChecker());

/// Provider — call `ref.read(updateInfoProvider.notifier).runOnce()` from
/// `main.dart` after bootstrap to fire the FR-068 one-per-launch check.
///
/// The Notifier subclass takes a no-arg constructor (review fix M-A5) and
/// pulls its dependencies through [ref] so feature widgets that want to
/// stub the release feed for testing only need to override
/// `releaseFeedCheckerProvider`.
class UpdateInfoNotifier extends Notifier<UpdateInfo> {
  late final String _installedVersion;
  late final ReleaseFeedChecker _checker;
  bool _hasRun = false;

  String get installedVersion => _installedVersion;

  @override
  UpdateInfo build() {
    _installedVersion = ref.watch(installedAppVersionProvider);
    _checker = ref.watch(releaseFeedCheckerProvider);
    return UpdateInfo(
      state: UpdateState.unknown,
      installedVersion: _installedVersion,
    );
  }

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
        installedVersion: _installedVersion,
        lastCheckedAt: now,
      );
      return;
    }
    final available = _isNewer(feed.version, _installedVersion);
    state = UpdateInfo(
      state: available ? UpdateState.updateAvailable : UpdateState.upToDate,
      installedVersion: _installedVersion,
      feed: feed,
      lastCheckedAt: now,
    );
  }

  /// Returns true when `advertised` is strictly newer than `installed`.
  /// Naive numeric-segment comparison ("1.2.3" > "1.2.2") — sufficient for
  /// the MVP since the release-feed schema enforces the same regex used
  /// by [ReleaseFeed.fromJson].
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

/// FR-068 — single shared UpdateInfoNotifier instance.
///
/// **Round-3 analyze D1 (2026-05-24)**: the `UpdateInfoNotifier`
/// class was defined in T036 but its `NotifierProvider` was never
/// declared — only referenced in the docstring at line 148. This
/// gap meant Phase-9 `VersionBadge` had to invent its own
/// release-feed provider, duplicating the FR-068 "at most once per
/// launch" path. The provider declaration here is the single source
/// of truth for `state` + `runOnce()`.
final updateInfoProvider =
    NotifierProvider<UpdateInfoNotifier, UpdateInfo>(
  UpdateInfoNotifier.new,
);
