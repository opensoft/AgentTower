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
/// `sourceScope`, `targetRule`, and `masterRule` are open vocabularies
/// on the daemon side (FEAT-009 owns them). The app treats them as
/// opaque strings and renders them verbatim — there is intentionally no
/// app-side parsing of rule semantics, so future FEAT-009 rule-grammar
/// changes do not require an app rebuild.
@freezed
class Route with _$Route {
  const factory Route({
    required String routeId,
    required String sourceScope,
    required String targetRule,
    required String masterRule,
    required bool enabled,
    String? recentSkipExplanation,
    String? recentMatchSummary,
    required DateTime asOf,
  }) = _Route;

  factory Route.fromJson(Map<String, dynamic> json) => _$RouteFromJson(json);
}
