import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/json_utils.dart';
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
  // Stamp asOf ONCE per page rather than per-row (review fix H3 / arch lane).
  // Per-row stamping defeated freezed equality and forced every downstream
  // Consumer to rebuild on every refetch.
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => model.Container.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final containerDetailProvider =
    FutureProvider.autoDispose.family<model.Container, String>(
  (ref, containerId) async {
    final raw = await ref
        .watch(appClientProvider)
        .containerDetail(containerId);
    return model.Container.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
  },
);

// =================================================================== Panes

final paneListProvider = FutureProvider.autoDispose<List<Pane>>((ref) async {
  final page = await ref.watch(appClientProvider).paneList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => Pane.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final paneDetailProvider =
    FutureProvider.autoDispose.family<Pane, String>((ref, paneId) async {
  final raw = await ref.watch(appClientProvider).paneDetail(paneId);
  return Pane.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
});

// ================================================================== Agents

final agentListProvider =
    FutureProvider.autoDispose<List<AdoptedAgent>>((ref) async {
  final page = await ref.watch(appClientProvider).agentList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => AdoptedAgent.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final agentDetailProvider =
    FutureProvider.autoDispose.family<AdoptedAgent, String>(
  (ref, agentId) async {
    final raw = await ref.watch(appClientProvider).agentDetail(agentId);
    return AdoptedAgent.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
  },
);

// ================================================================== Events

final eventListProvider =
    FutureProvider.autoDispose<List<model.Event>>((ref) async {
  final page = await ref.watch(appClientProvider).eventList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => model.Event.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

// =================================================================== Queue

final queueListProvider =
    FutureProvider.autoDispose<List<QueueRow>>((ref) async {
  final page = await ref.watch(appClientProvider).queueList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => QueueRow.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

// ================================================================== Routes

final routeListProvider =
    FutureProvider.autoDispose<List<model.Route>>((ref) async {
  final page = await ref.watch(appClientProvider).routeList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => model.Route.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

// =============================================================== Readiness

final readinessProvider = FutureProvider.autoDispose<Map<String, dynamic>>(
  (ref) => ref.watch(appClientProvider).readiness(),
);

// ====================================================== Internal helpers
//
// `as_of` stamping is centralized in `core/json_utils.dart`
// (`withAsOfDefault`). A SHARED page-fetch `asOf` is passed so every row
// in a page shares one timestamp (per-row `DateTime.now()` would defeat
// freezed equality across rebuilds — review fix H3 / arch lane). The
// shared helper guards on a *usable* value, not mere key presence, so a
// present-but-empty `as_of` degrades to a stamped default instead of
// throwing inside the freezed `DateTime.parse`.
