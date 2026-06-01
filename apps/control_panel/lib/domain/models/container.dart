import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'container.freezed.dart';
part 'container.g.dart';

/// FEAT-011 `app.container` mirror. T057 (Phase 3 US1) + data-model §1.16.
///
/// Read-only mirror of FEAT-011's container shape. The app NEVER mutates
/// containers locally — every projection comes from `app.container.list`
/// / `app.container.detail`. `asOf` records the daemon-side timestamp
/// for the snapshot so stale-data rendering can apply the FR-004
/// `runtime-unreachable` treatment.
@freezed
class Container with _$Container {
  const factory Container({
    required String containerId,
    required String name,
    @JsonKey(unknownEnumValue: ContainerState.unknown)
    required ContainerState state,
    required String projectPath,
    required DateTime discoveredAt,
    required DateTime asOf,
  }) = _Container;

  factory Container.fromJson(Map<String, dynamic> json) =>
      _$ContainerFromJson(json);
}
