import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// FR-025 / FR-056 — unread notification count badges. T141 (Phase 8
/// US6).
///
/// Two variants:
///   - [ProjectUnreadBadge] — per-project badge rendered on the
///     project card; takes a project id.
///   - [GlobalUnreadBadge] — global badge rendered in the AppBar
///     (no project filter; counts unread across all projects).
class ProjectUnreadBadge extends ConsumerWidget {
  const ProjectUnreadBadge({super.key, required this.projectId});
  final String projectId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(unreadNotificationCountProvider(projectId));
    return count.when(
      data: (n) => n == 0 ? const SizedBox.shrink() : _Pill(count: n),
      loading: () => const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
    );
  }
}

class GlobalUnreadBadge extends ConsumerWidget {
  const GlobalUnreadBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(unreadNotificationCountProvider(null));
    return count.when(
      data: (n) => n == 0
          ? const Icon(Icons.notifications_none)
          : Stack(
              clipBehavior: Clip.none,
              children: [
                const Icon(Icons.notifications_active),
                Positioned(
                  right: -6,
                  top: -6,
                  child: _Pill(count: n),
                ),
              ],
            ),
      loading: () => const Icon(Icons.notifications_none),
      error: (_, __) => const Icon(Icons.notifications_none),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.error,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        count > 99 ? '99+' : '$count',
        style: TextStyle(
          color: Theme.of(context).colorScheme.onError,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
