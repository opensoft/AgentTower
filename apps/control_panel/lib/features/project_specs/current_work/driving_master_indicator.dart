import 'package:flutter/material.dart';

import '../../../core/l10n/app_localizations.dart';

/// FR-029 "agent X is driving FEAT-N under handoff H" indicator. T092
/// (Phase 4 US2).
///
/// Renders the canonical attribution sentence on every feature
/// surface that has a current driver. One-click navigation hooks
/// (`onOpenMaster`, `onOpenHandoff`) are exposed so callers wire
/// them per surface (Current Work → master detail, Specs → handoff
/// detail, etc.).
///
/// Multi-driver display: when [conflictingDrivers] is non-empty, an
/// inline warning chip is appended ("⚠ conflict: …") so the operator
/// notices contention before drilling in.
class DrivingMasterIndicator extends StatelessWidget {
  const DrivingMasterIndicator({
    super.key,
    required this.masterLabel,
    required this.featureChangeDisplayId,
    this.handoffId,
    this.conflictingDrivers = const <String>[],
    this.onOpenMaster,
    this.onOpenHandoff,
  });

  /// The driving master's operator label.
  final String masterLabel;

  /// The driven feature/change's display id (e.g. "FEAT-012").
  final String featureChangeDisplayId;

  /// The handoff id under which the driver is operating, if known.
  final String? handoffId;

  /// Additional masters claiming the same feature/change. Empty
  /// in the happy path.
  final List<String> conflictingDrivers;

  final VoidCallback? onOpenMaster;
  final VoidCallback? onOpenHandoff;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final hasConflict = conflictingDrivers.isNotEmpty;
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 6,
      children: [
        Icon(Icons.psychology, size: 16, color: theme.colorScheme.primary),
        InkWell(
          onTap: onOpenMaster,
          child: Text(
            masterLabel,
            style: theme.textTheme.bodyMedium?.copyWith(
              decoration: onOpenMaster == null
                  ? null
                  : TextDecoration.underline,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        Text(l10n.drivingMasterIsDriving, style: theme.textTheme.bodyMedium),
        Text(
          featureChangeDisplayId,
          style: theme.textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.w600,
          ),
        ),
        if (handoffId != null) ...[
          Text(l10n.drivingMasterUnder, style: theme.textTheme.bodyMedium),
          InkWell(
            onTap: onOpenHandoff,
            child: Text(
              handoffId!,
              style: theme.textTheme.bodyMedium?.copyWith(
                decoration: onOpenHandoff == null
                    ? null
                    : TextDecoration.underline,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
        if (hasConflict)
          Tooltip(
            message: l10n.drivingMasterConflictTooltip(
                conflictingDrivers.join(", ")),
            child: Chip(
              avatar: const Icon(Icons.warning, size: 14),
              label: Text(l10n.drivingMasterConflictChipLabel),
              padding: EdgeInsets.zero,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              visualDensity: VisualDensity.compact,
            ),
          ),
      ],
    );
  }
}
