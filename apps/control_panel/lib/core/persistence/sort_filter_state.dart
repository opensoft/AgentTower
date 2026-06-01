import 'package:collection/collection.dart';

import '../../domain/models/common_enums.dart';

/// `ListSortFilterState` — the persisted per-view sort + filter slice
/// (FR-078). T179 (Phase 9 Polish).
///
/// Mirrors the `ListSortFilterState` wire shape documented in
/// `contracts/ux-state.md` §1:
///
/// ```json
/// { "sort_field": "<column id>", "sort_direction": "asc"|"desc",
///   "filters": { /* view-specific, opaque */ } }
/// ```
///
/// Hand-written (no codegen) to match the sibling persistence/config model
/// [Settings]. The persistence layer treats [filters] as an opaque
/// `Map<String, dynamic>`; each view validates its own filter keys on
/// deserialize and silently resets unknown values to default per the
/// contract's "reject + log" rule (FR-074).
class ListSortFilterState {
  const ListSortFilterState({
    this.sortField,
    this.sortDirection = SortDirection.desc,
    this.filters = const <String, dynamic>{},
  });

  /// View-specific column id the operator sorted by, or `null` for the
  /// view's default ordering.
  final String? sortField;

  /// Sort direction. Defaults to [SortDirection.desc].
  final SortDirection sortDirection;

  /// Opaque, view-specific filter selections (e.g. `{ "status": "new" }`).
  final Map<String, dynamic> filters;

  /// The neutral "no selection" state — equivalent to a view that has never
  /// been sorted or filtered. Persisting [empty] removes the view's entry.
  static const ListSortFilterState empty = ListSortFilterState();

  /// `true` when there is nothing meaningful to persist (default order,
  /// no active filters). Used by [SortFilterRepository.save] to prune the
  /// entry rather than store a no-op.
  bool get isEmpty => sortField == null && filters.isEmpty;

  /// Tolerant parse. An unknown `sort_direction` falls back to [desc]
  /// rather than throwing, so a daemon-side enum change can't corrupt a
  /// whole view's persisted state (contract §1 "reject + reset to default").
  factory ListSortFilterState.fromJson(Map<String, dynamic> json) {
    final dirRaw = json['sort_direction'] as String?;
    SortDirection dir = SortDirection.desc;
    if (dirRaw != null) {
      for (final d in SortDirection.values) {
        if (d.wireValue == dirRaw) {
          dir = d;
          break;
        }
      }
    }
    final rawFilters = json['filters'];
    return ListSortFilterState(
      sortField: json['sort_field'] as String?,
      sortDirection: dir,
      filters: rawFilters is Map<String, dynamic>
          ? Map<String, dynamic>.from(rawFilters)
          : const <String, dynamic>{},
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        if (sortField != null) 'sort_field': sortField,
        'sort_direction': sortDirection.wireValue,
        'filters': filters,
      };

  ListSortFilterState copyWith({
    String? sortField,
    SortDirection? sortDirection,
    Map<String, dynamic>? filters,
  }) =>
      ListSortFilterState(
        sortField: sortField ?? this.sortField,
        sortDirection: sortDirection ?? this.sortDirection,
        filters: filters ?? this.filters,
      );

  static const _eq = DeepCollectionEquality();

  @override
  bool operator ==(Object other) =>
      other is ListSortFilterState &&
      other.sortField == sortField &&
      other.sortDirection == sortDirection &&
      _eq.equals(other.filters, filters);

  @override
  int get hashCode => Object.hash(
        sortField,
        sortDirection,
        _eq.hash(filters),
      );
}
