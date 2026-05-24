import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/app_client.dart';
import '../../core/providers.dart';
import '../../domain/models/adopted_agent.dart';
import '../../domain/models/container.dart' as model;
import '../../domain/models/event.dart' as model;
import '../../domain/models/pane.dart';
import '../../domain/models/queue_row.dart';
import '../../domain/models/route.dart' as model;

/// Riverpod providers for the US1 Agent Operations surfaces.
/// T065+ (Phase 3 US1).
///
/// Each `*ListProvider` is a `FutureProvider.autoDispose` that fetches
/// the first page (limit 50, FEAT-011 default). Pagination + live
/// updates land in Phase 9 polish — for the MVP, sub-views fetch
/// once on mount and the operator can hit "refresh" to re-fetch.
///
/// A `*DetailProvider` family is keyed on the entity id so individual
/// drill-down screens can subscribe without re-fetching the entire
/// list. The list provider invalidates the detail family when a
/// mutation completes so the drill-down stays in sync.

// ============================================================ Dashboard

final dashboardProvider = FutureProvider.autoDispose<Map<String, dynamic>>(
  (ref) => ref.watch(appClientProvider).dashboard(),
);

// ============================================================== Containers

final containerListProvider =
    FutureProvider.autoDispose<List<model.Container>>((ref) async {
  final page = await ref.watch(appClientProvider).containerList();
  return _parseContainers(page);
});

final containerDetailProvider =
    FutureProvider.autoDispose.family<model.Container, String>(
  (ref, containerId) async {
    final raw = await ref
        .watch(appClientProvider)
        .containerDetail(containerId);
    return model.Container.fromJson(_withAsOf(raw));
  },
);

// =================================================================== Panes

final paneListProvider = FutureProvider.autoDispose<List<Pane>>((ref) async {
  final page = await ref.watch(appClientProvider).paneList();
  return page.items
      .map((m) => Pane.fromJson(_withAsOf(m)))
      .toList(growable: false);
});

final paneDetailProvider =
    FutureProvider.autoDispose.family<Pane, String>((ref, paneId) async {
  final raw = await ref.watch(appClientProvider).paneDetail(paneId);
  return Pane.fromJson(_withAsOf(raw));
});

// ================================================================== Agents

final agentListProvider =
    FutureProvider.autoDispose<List<AdoptedAgent>>((ref) async {
  final page = await ref.watch(appClientProvider).agentList();
  return page.items
      .map((m) => AdoptedAgent.fromJson(_withAsOf(m)))
      .toList(growable: false);
});

final agentDetailProvider =
    FutureProvider.autoDispose.family<AdoptedAgent, String>(
  (ref, agentId) async {
    final raw = await ref.watch(appClientProvider).agentDetail(agentId);
    return AdoptedAgent.fromJson(_withAsOf(raw));
  },
);

// ================================================================== Events

final eventListProvider =
    FutureProvider.autoDispose<List<model.Event>>((ref) async {
  final page = await ref.watch(appClientProvider).eventList();
  return page.items
      .map((m) => model.Event.fromJson(_withAsOf(m)))
      .toList(growable: false);
});

// =================================================================== Queue

final queueListProvider =
    FutureProvider.autoDispose<List<QueueRow>>((ref) async {
  final page = await ref.watch(appClientProvider).queueList();
  return page.items
      .map((m) => QueueRow.fromJson(_withAsOf(m)))
      .toList(growable: false);
});

// ================================================================== Routes

final routeListProvider =
    FutureProvider.autoDispose<List<model.Route>>((ref) async {
  final page = await ref.watch(appClientProvider).routeList();
  return page.items
      .map((m) => model.Route.fromJson(_withAsOf(m)))
      .toList(growable: false);
});

// =============================================================== Readiness

final readinessProvider = FutureProvider.autoDispose<Map<String, dynamic>>(
  (ref) => ref.watch(appClientProvider).readiness(),
);

// ====================================================== Internal helpers

/// Stamps an `asOf` field onto an entity payload if the daemon didn't
/// already supply one. The freezed models all require `asOf`; using
/// "now" client-side is correct for live data (the daemon's response
/// IS the most-recent snapshot the app has seen).
Map<String, dynamic> _withAsOf(Map<String, dynamic> raw) {
  if (raw.containsKey('as_of') || raw.containsKey('asOf')) return raw;
  return {
    ...raw,
    'as_of': DateTime.now().toUtc().toIso8601String(),
  };
}

List<model.Container> _parseContainers(PagedResult page) => page.items
    .map((m) => model.Container.fromJson(_withAsOf(m)))
    .toList(growable: false);
