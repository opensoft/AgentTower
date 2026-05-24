import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

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
final releaseFeedCheckProvider =
    FutureProvider<ReleaseFeed?>((ref) async {
  try {
    return await ReleaseFeedChecker().fetch();
  } catch (_) {
    // Silent failure per R-12: the release-feed is informational.
    return null;
  }
});

/// Compact Dashboard badge — "v0.1.0" + an exclamation icon if a
/// newer release is advertised.
class VersionBadge extends ConsumerWidget {
  const VersionBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pkg = ref.watch(packageInfoProvider);
    final feed = ref.watch(releaseFeedCheckProvider);
    return pkg.when(
      data: (info) {
        final theme = Theme.of(context);
        final updateAvailable = feed.maybeWhen(
          data: (f) => f != null && f.version != info.version,
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
                ? 'v${info.version} → v$remoteVersion'
                : 'v${info.version}',
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
    return pkg.when(
      data: (info) {
        final remote = feed.maybeWhen(
          data: (f) => f,
          orElse: () => null,
        );
        final updateAvailable =
            remote != null && remote.version != info.version;
        return ListTile(
          leading: Icon(
            updateAvailable
                ? Icons.system_update
                : Icons.verified_outlined,
            color: updateAvailable
                ? Theme.of(context).colorScheme.error
                : null,
          ),
          title: Text('Installed version v${info.version}'),
          subtitle: Text(
            updateAvailable
                ? 'Update available: v${remote.version} '
                    '(released ${remote.releasedAt.toLocal()})'
                : 'You are on the latest version.',
          ),
          trailing: updateAvailable && remote.releaseNotesUrl.isNotEmpty
              ? TextButton(
                  onPressed: () =>
                      SafeUrlLauncher.open(context, remote.releaseNotesUrl),
                  child: const Text('Release notes'),
                )
              : null,
        );
      },
      loading: () => const ListTile(
        leading: Icon(Icons.hourglass_empty),
        title: Text('Checking app version…'),
      ),
      error: (e, _) => ListTile(
        leading: const Icon(Icons.error_outline),
        title: const Text('Version unavailable'),
        subtitle: Text('$e'),
      ),
    );
  }
}
