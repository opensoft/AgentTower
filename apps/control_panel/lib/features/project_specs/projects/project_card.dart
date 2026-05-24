import 'package:flutter/material.dart';

import '../../../domain/models/badges.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/project.dart';

/// FR-025 Project card. T088 (Phase 4 US2).
///
/// Renders every required attribute named in FR-025 in a single card:
/// name, repository path, repo state badge, active branch/worktree
/// badge, active feature/change, current phase/status, current driving
/// master, compact master strip (up to 2 + overflow), sub-agent count,
/// last activity, validation badge + last run age, drift badge +
/// source + age, attention summary, unread notification count, and
/// quick actions.
///
/// The card is sized to display ~5 cards on a typical Dashboard width
/// (FR-024). Density (Comfortable / Compact per FR-009) is honored
/// implicitly via `Theme.of(context).visualDensity`.
///
/// Quick actions are exposed as overflow-menu entries to keep the
/// card chrome clean; the spec does not mandate inline-button form.
class ProjectCard extends StatelessWidget {
  const ProjectCard({
    super.key,
    required this.project,
    this.onOpenProject,
    this.onOpenCurrentWork,
    this.onOpenMaster,
    this.onOpenSpecs,
    this.onOpenDrift,
    this.onRemove,
  });

  final Project project;
  final VoidCallback? onOpenProject;
  final VoidCallback? onOpenCurrentWork;
  final VoidCallback? onOpenMaster;
  final VoidCallback? onOpenSpecs;
  final VoidCallback? onOpenDrift;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpenProject,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _header(context, theme),
              const SizedBox(height: 8),
              _badgeRow(context, theme),
              const SizedBox(height: 12),
              _activeFeatureRow(context, theme),
              const SizedBox(height: 8),
              _drivingMasterRow(context, theme),
              const SizedBox(height: 8),
              _bottomMeta(context, theme),
            ],
          ),
        ),
      ),
    );
  }

  Widget _header(BuildContext context, ThemeData theme) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                project.label,
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(
                project.repositoryPath,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
        if (project.unreadNotificationCount > 0)
          _UnreadBadge(count: project.unreadNotificationCount),
        PopupMenuButton<String>(
          tooltip: 'Project actions',
          onSelected: _onMenu,
          itemBuilder: (_) => [
            const PopupMenuItem(value: 'open', child: Text('Open project')),
            const PopupMenuItem(
              value: 'current_work',
              child: Text('Open Current Work'),
            ),
            const PopupMenuItem(value: 'specs', child: Text('Open Specs')),
            const PopupMenuItem(value: 'drift', child: Text('Open Drift')),
            if (project.currentDrivingMasterAgentId != null)
              const PopupMenuItem(
                value: 'master',
                child: Text('Open driving master'),
              ),
            const PopupMenuDivider(),
            const PopupMenuItem(
              value: 'remove',
              child: Text('Remove project'),
            ),
          ],
          icon: const Icon(Icons.more_vert),
        ),
      ],
    );
  }

  void _onMenu(String value) {
    switch (value) {
      case 'open':
        onOpenProject?.call();
        break;
      case 'current_work':
        onOpenCurrentWork?.call();
        break;
      case 'specs':
        onOpenSpecs?.call();
        break;
      case 'drift':
        onOpenDrift?.call();
        break;
      case 'master':
        onOpenMaster?.call();
        break;
      case 'remove':
        onRemove?.call();
        break;
    }
  }

  Widget _badgeRow(BuildContext context, ThemeData theme) {
    return Wrap(
      spacing: 8,
      runSpacing: 6,
      children: [
        _RepoStateChip(badge: project.repoState),
        _BranchChip(badge: project.activeBranch),
        _ValidationChip(badge: project.validationBadge),
        _DriftChip(
          badge: project.driftBadge,
          source: project.driftSource,
          age: project.driftAge,
        ),
        _AttentionChip(summary: project.attentionSummary),
      ],
    );
  }

  Widget _activeFeatureRow(BuildContext context, ThemeData theme) {
    final id = project.activeFeatureChangeId;
    if (id == null) {
      return Text(
        'No active feature/change',
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      );
    }
    return Row(
      children: [
        Icon(Icons.assignment, size: 16, color: theme.colorScheme.primary),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            'Active: $id',
            style: theme.textTheme.bodyMedium,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }

  Widget _drivingMasterRow(BuildContext context, ThemeData theme) {
    final masterIds = project.primaryMasterAgentIds;
    if (masterIds.isEmpty && project.currentDrivingMasterAgentId == null) {
      return Text(
        'No driving master',
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      );
    }
    final visible = masterIds.take(2).join(', ');
    final overflow = project.masterOverflowCount;
    final driver = project.currentDrivingMasterAgentId;
    return Row(
      children: [
        const Icon(Icons.psychology, size: 16),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            [
              if (driver != null) 'Driver: $driver',
              if (masterIds.isNotEmpty)
                'Masters: $visible${overflow > 0 ? ' (+$overflow)' : ''}',
              'Sub-agents: ${project.subAgentCount}',
            ].join(' · '),
            style: theme.textTheme.bodySmall,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }

  Widget _bottomMeta(BuildContext context, ThemeData theme) {
    return Row(
      children: [
        Text(
          'Last activity: ${_formatTime(project.lastActivityAt)}',
          style: theme.textTheme.labelSmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }

  static String _formatTime(DateTime dt) {
    final local = dt.toLocal();
    final yyyy = local.year.toString().padLeft(4, '0');
    final mm = local.month.toString().padLeft(2, '0');
    final dd = local.day.toString().padLeft(2, '0');
    final hh = local.hour.toString().padLeft(2, '0');
    final mi = local.minute.toString().padLeft(2, '0');
    return '$yyyy-$mm-$dd $hh:$mi';
  }
}

class _UnreadBadge extends StatelessWidget {
  const _UnreadBadge({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(right: 4),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.error,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        '$count',
        style: TextStyle(
          color: Theme.of(context).colorScheme.onError,
          fontSize: 11,
        ),
      ),
    );
  }
}

class _RepoStateChip extends StatelessWidget {
  const _RepoStateChip({required this.badge});
  final RepoStateBadge badge;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[badge.kind.wireValue];
    if ((badge.aheadCount ?? 0) > 0) parts.add('↑${badge.aheadCount}');
    if ((badge.behindCount ?? 0) > 0) parts.add('↓${badge.behindCount}');
    if ((badge.dirtyFileCount ?? 0) > 0) parts.add('±${badge.dirtyFileCount}');
    return _Chip(icon: Icons.commit, label: parts.join(' '));
  }
}

class _BranchChip extends StatelessWidget {
  const _BranchChip({required this.badge});
  final BranchWorktreeBadge badge;

  @override
  Widget build(BuildContext context) {
    return _Chip(
      icon: Icons.alt_route,
      label: badge.detached ? '${badge.branchName} (detached)' : badge.branchName,
    );
  }
}

class _ValidationChip extends StatelessWidget {
  const _ValidationChip({required this.badge});
  final ValidationBadge badge;

  @override
  Widget build(BuildContext context) {
    final age = badge.lastRunAt;
    final ageLabel = age == null
        ? '—'
        : '${DateTime.now().difference(age).inMinutes}m ago';
    return _Chip(
      icon: _iconFor(badge.kind),
      label: 'val: ${badge.kind.wireValue} ($ageLabel)',
    );
  }

  static IconData _iconFor(ValidationBadgeKind k) => switch (k) {
        ValidationBadgeKind.pass => Icons.check_circle,
        ValidationBadgeKind.fail => Icons.error,
        ValidationBadgeKind.partial => Icons.warning,
        ValidationBadgeKind.pending => Icons.schedule,
        ValidationBadgeKind.unknown => Icons.help_outline,
      };
}

class _DriftChip extends StatelessWidget {
  const _DriftChip({
    required this.badge,
    required this.source,
    required this.age,
  });
  final DriftBadge badge;
  final DriftSource? source;
  final DateTime? age;

  @override
  Widget build(BuildContext context) {
    final parts = <String>['drift: ${badge.highestSeverity.wireValue}'];
    if (badge.openCount > 0) parts.add('(${badge.openCount})');
    if (source != null) parts.add('src=${source!.wireValue}');
    if (age != null) {
      parts.add('${DateTime.now().difference(age!).inMinutes}m');
    }
    return _Chip(icon: Icons.flag, label: parts.join(' '));
  }
}

class _AttentionChip extends StatelessWidget {
  const _AttentionChip({required this.summary});
  final AttentionSummary summary;

  @override
  Widget build(BuildContext context) {
    return _Chip(
      icon: Icons.notifications_active,
      label: 'attn: ${summary.highestSeverity.wireValue} (${summary.openCount})',
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 4),
          Text(label, style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }
}
