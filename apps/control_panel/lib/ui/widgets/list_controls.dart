import 'package:flutter/material.dart';

/// Tolerant wire→value decode for a persisted single-value filter. Returns
/// `null` on any mismatch (FR-078 "reject a removed value + reset to
/// default"). Used by the T180 list views when seeding their filter from
/// the persisted [ListSortFilterState].
T? filterValueFromWire<T>(
  Object? wire,
  List<T> options,
  String Function(T) wireOf,
) {
  if (wire == null) return null;
  final s = wire.toString();
  for (final o in options) {
    if (wireOf(o) == s) return o;
  }
  return null;
}

/// Reusable list sort/filter controls. T180 (Phase 9 / FR-078).
///
/// The Agent-Ops list views (Containers, Panes, Agents, Events, Queue,
/// Routes) are hosted bare inside the shell's Scaffold and have no AppBar
/// of their own, so [ListControlsBar] gives them a slim right-aligned
/// header strip to host filter/sort menus above the list. Views that own
/// an AppBar (Projects, Available Validation, Drift, Runs) put the same
/// menus directly in `AppBar.actions` instead.
///
/// Labels are passed in as plain strings rather than read from
/// `AppLocalizations` so the widget works in both localized surfaces
/// (which pass `l10n.*`) and the not-yet-localized Agent-Ops views (which
/// pass raw strings pending the FR-067 sweep tracked as T181). The widget
/// itself adds no hardcoded user-facing prose.
class ListControlsBar extends StatelessWidget {
  const ListControlsBar({super.key, required this.controls});

  final List<Widget> controls;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: controls,
        ),
      ),
    );
  }
}

/// A "filter by a single value (or All)" popup menu. `T` is the filter
/// dimension — an enum (e.g. `PaneState`), a `bool` (Routes enabled), or a
/// `String` (open-vocabulary event types). A `null` selection means "All".
class EnumFilterMenu<T> extends StatelessWidget {
  const EnumFilterMenu({
    super.key,
    required this.tooltip,
    required this.allLabel,
    required this.value,
    required this.options,
    required this.labelOf,
    required this.onSelected,
  });

  /// Tooltip on the trigger button.
  final String tooltip;

  /// Label for the "no filter" menu entry.
  final String allLabel;

  /// Current selection, or `null` for "All".
  final T? value;

  /// Selectable values.
  final List<T> options;

  /// Renders a menu label for a value.
  final String Function(T) labelOf;

  /// Called with the new selection (`null` clears the filter).
  final ValueChanged<T?> onSelected;

  @override
  Widget build(BuildContext context) {
    final active = value != null;
    return PopupMenuButton<_FilterChoice<T>>(
      tooltip: tooltip,
      icon: Icon(
        active ? Icons.filter_alt : Icons.filter_alt_outlined,
        color: active ? Theme.of(context).colorScheme.primary : null,
      ),
      onSelected: (choice) => onSelected(choice.value),
      itemBuilder: (_) => <PopupMenuEntry<_FilterChoice<T>>>[
        CheckedPopupMenuItem<_FilterChoice<T>>(
          value: _FilterChoice<T>(null),
          checked: value == null,
          child: Text(allLabel),
        ),
        for (final o in options)
          CheckedPopupMenuItem<_FilterChoice<T>>(
            value: _FilterChoice<T>(o),
            checked: value == o,
            child: Text(labelOf(o)),
          ),
      ],
    );
  }
}

/// Centered placeholder shown when an active filter excludes every row
/// (the underlying list is non-empty). [message] is supplied by the caller
/// so each view can word it appropriately (and localize when applicable).
class FilterNoMatch extends StatelessWidget {
  const FilterNoMatch({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(message, textAlign: TextAlign.center),
      ),
    );
  }
}

/// Wrapper so a `null` ("All") selection is representable as a distinct,
/// non-null menu value (a bare `null` PopupMenuItem value is ambiguous).
class _FilterChoice<T> {
  const _FilterChoice(this.value);
  final T? value;

  @override
  bool operator ==(Object other) =>
      other is _FilterChoice<T> && other.value == value;

  @override
  int get hashCode => value.hashCode;
}
