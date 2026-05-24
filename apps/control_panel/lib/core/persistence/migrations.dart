/// Forward-only schema migrations for ux-state.json. T018 (Phase 2 Foundational).
///
/// Per research R-21: migrations are an ordered list of [Migration]
/// `{fromVersion, toVersion, transform}`. On launch, if the persisted
/// state's `schema_version` is older than the app's current version, the
/// migrations are applied in order. If newer, the state is treated as
/// incompatible per FR-070 and dropped.
///
/// MVP ships at schema_version = 1 with NO migrations registered. The
/// framework is in place so adding a v2 migration is a one-line drop.
typedef MigrationTransform = Map<String, dynamic> Function(
  Map<String, dynamic> input,
);

class Migration {
  const Migration({
    required this.fromVersion,
    required this.toVersion,
    required this.transform,
  });

  final int fromVersion;
  final int toVersion;
  final MigrationTransform transform;
}

class MigrationRegistry {
  static const int currentSchemaVersion = 1;

  /// Ordered migrations from older versions to [currentSchemaVersion].
  /// Empty at MVP (schema_version = 1).
  static const List<Migration> migrations = [];

  /// Applies registered migrations to bring [input] from [fromVersion] up
  /// to [currentSchemaVersion]. Returns the transformed map.
  ///
  /// Throws [StateError] if no migration path exists (i.e. [fromVersion]
  /// is newer than [currentSchemaVersion] OR there's a gap in the path).
  static Map<String, dynamic> applyMigrations(
    Map<String, dynamic> input,
    int fromVersion,
  ) {
    if (fromVersion > currentSchemaVersion) {
      throw StateError(
        'Persisted schema_version $fromVersion is newer than '
        'current $currentSchemaVersion; persisted state is dropped per FR-070.',
      );
    }
    var current = input;
    var version = fromVersion;
    while (version < currentSchemaVersion) {
      final next = migrations.firstWhere(
        (m) => m.fromVersion == version,
        orElse: () => throw StateError(
          'No migration registered from version $version to '
          '${version + 1}; cannot continue.',
        ),
      );
      current = next.transform(current);
      version = next.toVersion;
    }
    return current;
  }
}
