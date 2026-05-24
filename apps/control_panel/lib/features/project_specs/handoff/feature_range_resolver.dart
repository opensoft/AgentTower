import '../../../domain/models/common_enums.dart';
import '../../../domain/models/resolved_work_item.dart';

/// FR-039 — canonical `FEAT-N..FEAT-M` range expansion. T103 (Phase 5 US3).
///
/// **Canonical syntax (per F8 sub-edit)**: `FEAT-N..FEAT-M`, inclusive at
/// both ends; ascending numeric order regardless of input order
/// (i.e. `FEAT-12..FEAT-8` resolves the same as `FEAT-8..FEAT-12`).
///
/// **Excluded items (F7-c)**: items in the range that are `deferred`
/// or `merged` are kept in the resolved list with [ResolvedExclusion]
/// populated; they are NOT silently omitted. The master receives the
/// annotated entry so the operator's range intent is reproducible.
///
/// The resolver itself is a pure function over (a) the range syntax
/// the operator typed and (b) a daemon-supplied catalog of all
/// known feature/change ids with their stage. The catalog must come
/// from the daemon — the app never invents work-item ids.
class FeatureRangeResolver {
  const FeatureRangeResolver();

  /// Parses [rangeExpr] and resolves it against [catalog]. Returns
  /// the list in ascending numeric order, with deferred/merged items
  /// retained as annotated exclusions.
  ///
  /// Recognized forms:
  ///   - `FEAT-N`           → single feature
  ///   - `FEAT-N..FEAT-M`   → inclusive range (order-independent)
  ///   - `CHG-N`            → single change
  ///   - `CHG-N..CHG-M`     → inclusive change range
  ///
  /// Mixed feature+change ranges (e.g. `FEAT-1..CHG-3`) are rejected
  /// with [ArgumentError] — the kind prefix must match on both ends.
  List<ResolvedWorkItem> resolve({
    required String rangeExpr,
    required List<FeatureRangeCatalogEntry> catalog,
  }) {
    final expr = rangeExpr.trim();
    if (expr.isEmpty) return const <ResolvedWorkItem>[];

    final parts = expr.split('..');
    if (parts.length == 1) {
      return _resolveSingle(parts.first.trim(), catalog);
    }
    if (parts.length != 2) {
      throw ArgumentError(
        'Range expression must contain at most one ".." separator: $rangeExpr',
      );
    }

    final low = _parsePoint(parts[0].trim());
    final high = _parsePoint(parts[1].trim());
    if (low.prefix != high.prefix) {
      throw ArgumentError(
        'Range endpoints must share a kind prefix: '
        '${low.prefix} vs ${high.prefix}',
      );
    }
    final start = low.number < high.number ? low.number : high.number;
    final end = low.number < high.number ? high.number : low.number;

    final byId = {for (final e in catalog) e.displayId: e};
    final out = <ResolvedWorkItem>[];
    for (var n = start; n <= end; n++) {
      final id = '${low.prefix}-$n';
      final entry = byId[id];
      out.add(_resolvedFor(id, low.prefix, entry));
    }
    return out;
  }

  List<ResolvedWorkItem> _resolveSingle(
    String pointExpr,
    List<FeatureRangeCatalogEntry> catalog,
  ) {
    final point = _parsePoint(pointExpr);
    final byId = {for (final e in catalog) e.displayId: e};
    final entry = byId['${point.prefix}-${point.number}'];
    return [_resolvedFor('${point.prefix}-${point.number}', point.prefix, entry)];
  }

  _RangePoint _parsePoint(String s) {
    final m = RegExp(r'^([A-Z]+)-(\d+)$').firstMatch(s);
    if (m == null) {
      throw ArgumentError('Invalid range point: "$s" (expected e.g. FEAT-12)');
    }
    return _RangePoint(prefix: m.group(1)!, number: int.parse(m.group(2)!));
  }

  ResolvedWorkItem _resolvedFor(
    String displayId,
    String prefix,
    FeatureRangeCatalogEntry? entry,
  ) {
    final kind = prefix == 'FEAT' ? WorkItemKind.feature : WorkItemKind.change;
    if (entry == null) {
      // Unknown id in the range — surface as a deferred exclusion so the
      // operator notices the gap. The daemon catalog is the source of
      // truth; missing ids mean the work item doesn't exist or is not
      // visible to this operator.
      return ResolvedWorkItem(
        displayId: displayId,
        kind: kind,
        exclusion: ResolvedExclusion.deferred,
        note: 'not found in feature catalog',
      );
    }
    return ResolvedWorkItem(
      displayId: displayId,
      kind: kind,
      exclusion: _exclusionFor(entry.stage),
    );
  }

  static ResolvedExclusion? _exclusionFor(Stage stage) {
    return switch (stage) {
      Stage.deferred => ResolvedExclusion.deferred,
      Stage.merged => ResolvedExclusion.merged,
      _ => null,
    };
  }
}

class _RangePoint {
  const _RangePoint({required this.prefix, required this.number});
  final String prefix;
  final int number;
}

/// Catalog entry the resolver needs from the daemon: a display id +
/// its current stage (so deferred/merged exclusion can be applied).
class FeatureRangeCatalogEntry {
  const FeatureRangeCatalogEntry({
    required this.displayId,
    required this.stage,
  });
  final String displayId;
  final Stage stage;
}
