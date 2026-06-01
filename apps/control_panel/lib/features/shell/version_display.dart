import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../core/l10n/app_localizations.dart';
import '../../core/update/release_feed_check.dart';
import '../../ui/widgets/safe_url_launcher.dart';

/// FR-068 — installed app version display + update-available
/// indicator. T146 (Phase 9).
///
/// Rendered on the Dashboard (small badge) and Settings (full
/// list-tile). The release-feed check is the FR-068-permitted
/// outbound HTTPS GET (see FR-001 release-feed carve-out); it
/// is at-most-once-per-launch. When a newer version is advertised
/// the indicator links to the release page via SafeUrlLauncher.

/// Cache the package info per process — Flutter recommends fetching
/// once and reusing.
final packageInfoProvider = FutureProvider<PackageInfo>((ref) async {
  return PackageInfo.fromPlatform();
});

/// Triggers the FR-068 release-feed check exactly once per launch.
/// The provider's cached result is consumed by both the Dashboard
/// badge and the Settings tile, ensuring the at-most-once invariant.
///
/// Routes through [releaseFeedCheckerProvider] (the documented
/// test-override seam) rather than constructing [ReleaseFeedChecker]
/// directly, so widget tests can stub the feed and never hit the
/// real network.
final releaseFeedCheckProvider =
    FutureProvider<ReleaseFeed?>((ref) async {
  try {
    return await ref.watch(releaseFeedCheckerProvider).fetch();
  } catch (_) {
    // Silent failure per R-12: the release-feed is informational.
    return null;
  }
});

/// Returns true when `advertised` is strictly newer than `installed`.
///
/// FR-068 defines "update available" as the feed-advertised version
/// being *strictly greater* than the installed version, not merely
/// different. Mirrors `UpdateInfoNotifier._isNewer` (release_feed_check
/// .dart) — a naive numeric-segment comparison sufficient for the MVP,
/// where both strings satisfy the same version regex. A non-newer feed
/// (older, equal, or a build/suffix-only difference) must NOT flag an
/// update, so a `0.0.0-dev` dev build vs a `0.1.0` feed is handled
/// correctly while an older advertised version is not falsely flagged.
bool _isUpdateAvailable(String advertised, String installed) {
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

/// Compact AppBar badge — "v0.1.0" + an exclamation icon if a
/// newer release is advertised. Rendered globally on the AppShell
/// AppBar per Round-3 analyze C2 placement (was originally "Dashboard
/// badge" before the placement decision).
class VersionBadge extends ConsumerWidget {
  const VersionBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pkg = ref.watch(packageInfoProvider);
    final feed = ref.watch(releaseFeedCheckProvider);
    final l10n = AppLocalizations.of(context);
    return pkg.when(
      data: (info) {
        final theme = Theme.of(context);
        final updateAvailable = feed.maybeWhen(
          data: (f) =>
              f != null && _isUpdateAvailable(f.version, info.version),
          orElse: () => false,
        );
        final remoteVersion = feed.maybeWhen(
          data: (f) => f?.version,
          orElse: () => null,
        );
        final url = feed.maybeWhen(
          data: (f) => f?.releaseNotesUrl,
          orElse: () => null,
        );
        return TextButton.icon(
          icon: Icon(
            updateAvailable ? Icons.system_update : Icons.info_outline,
            size: 16,
            color: updateAvailable ? theme.colorScheme.error : null,
          ),
          label: Text(
            updateAvailable
                ? l10n.versionBadgeLabelUpdateAvailable(
                    info.version,
                    remoteVersion ?? '',
                  )
                : l10n.versionBadgeLabel(info.version),
          ),
          onPressed: updateAvailable && url != null && url.isNotEmpty
              ? () => SafeUrlLauncher.open(context, url)
              : null,
        );
      },
      loading: () => const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
    );
  }
}

/// Settings page tile — verbose form of [VersionBadge] with the
/// release-page link as a trailing action.
class VersionDisplayTile extends ConsumerWidget {
  const VersionDisplayTile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pkg = ref.watch(packageInfoProvider);
    final feed = ref.watch(releaseFeedCheckProvider);
    final l10n = AppLocalizations.of(context);
    return pkg.when(
      data: (info) {
        final remote = feed.maybeWhen(
          data: (f) => f,
          orElse: () => null,
        );
        final updateAvailable = remote != null &&
            _isUpdateAvailable(remote.version, info.version);
        return ListTile(
          leading: Icon(
            updateAvailable
                ? Icons.system_update
                : Icons.verified_outlined,
            color: updateAvailable
                ? Theme.of(context).colorScheme.error
                : null,
          ),
          title: Text(l10n.versionDisplayTileTitle(info.version)),
          subtitle: Text(
            updateAvailable
                ? l10n.versionDisplayTileSubtitleUpdateAvailable(
                    remote.version,
                    remote.releasedAt.toLocal().toString(),
                  )
                : l10n.versionDisplayTileSubtitleLatest,
          ),
          trailing: updateAvailable && remote.releaseNotesUrl.isNotEmpty
              ? TextButton(
                  onPressed: () =>
                      SafeUrlLauncher.open(context, remote.releaseNotesUrl),
                  child: Text(l10n.versionDisplayTileReleaseNotesButton),
                )
              : null,
        );
      },
      loading: () => ListTile(
        leading: const Icon(Icons.hourglass_empty),
        title: Text(l10n.versionDisplayTileLoadingTitle),
      ),
      error: (e, _) => ListTile(
        leading: const Icon(Icons.error_outline),
        title: Text(l10n.versionDisplayTileErrorTitle),
        subtitle: Text(l10n.versionDisplayTileErrorSubtitle(e.toString())),
      ),
    );
  }
}
