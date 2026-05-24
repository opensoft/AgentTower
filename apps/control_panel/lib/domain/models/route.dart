import 'package:freezed_annotation/freezed_annotation.dart';

part 'route.freezed.dart';
part 'route.g.dart';

/// FEAT-011 `app.route` mirror. T061 (Phase 3 US1) + data-model §1.16.
///
/// Routes are FEAT-009's source→target rule with optional master-rule
/// gating. The Routes view (T074) surfaces explainability per FR-021 +
/// FR-059 by rendering `recentSkipExplanation` whenever a route is
/// enabled but the operator has reason to wonder why a downstream
/// message didn't fire.
///
/// Field names match the FEAT-010 route definition (and the
/// `app.route.add` request shape on contract line 367):
///   - `sourceScope` — origin selector
///   - `template`    — operation template (e.g. `forward_event_to`)
///   - `target`      — destination selector
///
/// The earlier model used `targetRule` + `masterRule`; renamed to
/// match the contract (review fix C5 / spec-code lane). `masterRule`
/// is kept as an optional surface-side display field rather than a
/// wire field — the daemon does not currently echo a separate
/// `master_rule` key, but the Routes view shows it when present so
/// fixtures can populate it during US3+ work.
@freezed
class Route with _$Route {
  const factory Route({
    required String routeId,
    required String sourceScope,
    required String template,
    required String target,
    required bool enabled,
    String? masterRule,
    String? recentSkipExplanation,
    String? recentMatchSummary,
    required DateTime asOf,
  }) = _Route;

  factory Route.fromJson(Map<String, dynamic> json) => _$RouteFromJson(json);
}
