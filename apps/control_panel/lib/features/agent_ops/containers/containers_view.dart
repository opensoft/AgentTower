import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';

/// Agent Operations → Containers. T066 (Phase 3 US1) + FR-013.
/// Shows label, discovered status, project path per container.
class ContainersView extends ConsumerWidget {
  const ContainersView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final containers = ref.watch(containerListProvider);
    return containers.when(
      data: (rows) => rows.isEmpty
          ? const _Empty()
          : RefreshIndicator(
              onRefresh: () async => ref.invalidate(containerListProvider),
              child: ListView.builder(
                itemCount: rows.length,
                itemBuilder: (_, i) {
                  final c = rows[i];
                  return ListTile(
                    leading: Icon(_iconFor(c.state.wireValue)),
                    title: Text(c.name),
                    subtitle: Text('${c.projectPath} · ${c.state.wireValue}'),
                    trailing: Text(
                      c.containerId,
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  );
                },
              ),
            ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _ErrorState(
        error: e,
        onRetry: () => ref.invalidate(containerListProvider),
      ),
    );
  }

  static IconData _iconFor(String state) {
    return switch (state) {
      'running' => Icons.circle,
      'exited' => Icons.stop_circle_outlined,
      'paused' => Icons.pause_circle_outlined,
      'restarting' => Icons.refresh,
      _ => Icons.help_outline,
    };
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No containers discovered yet.\n\nLaunch a bench container with agenttowerd running '
          'and the Panes view will surface its tmux panes for adoption.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('Could not load containers: $error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
