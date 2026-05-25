import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/project_specs/handoff/helper_policy_resolver.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [HelperPolicyResolver]. Spec FR-038a +
/// `contracts/helper-policy.md` resolution rules + §6 absence-fallback
/// (FEAT-011 v1.0 R-19 caveat — when the daemon does not expose
/// `app.helper_policies.*`, the client falls back to a baked-default
/// snapshot).
///
/// The resolver depends on [appClientProvider]. We inject a fake client
/// that records calls and returns canned responses.

class _FakeAppClient extends AppClient {
  _FakeAppClient({
    this.listResponse,
    this.resolveResponse,
    this.resolveThrows,
  }) : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  /// What `helperPolicyList` should return.
  PagedResult? listResponse;

  /// What `helperPolicyResolve` should return (raw map).
  Map<String, dynamic>? resolveResponse;

  /// If non-null, `helperPolicyResolve` throws this instead of returning.
  Object? resolveThrows;

  /// Records the args of every resolve call.
  final List<({String projectId, String? operatorOverrideOfPolicyId})>
      resolveCalls = [];

  @override
  Future<PagedResult> helperPolicyList({String? cursorNext, int? limit}) async {
    return listResponse ??
        const PagedResult(items: <Map<String, dynamic>>[], cursorNext: null);
  }

  @override
  Future<Map<String, dynamic>> helperPolicyResolve({
    required String projectId,
    String? operatorOverrideOfPolicyId,
  }) async {
    resolveCalls.add((
      projectId: projectId,
      operatorOverrideOfPolicyId: operatorOverrideOfPolicyId,
    ));
    if (resolveThrows != null) throw resolveThrows!;
    return resolveResponse ?? const <String, dynamic>{};
  }
}

ProviderContainer _containerWith(_FakeAppClient client) {
  return ProviderContainer(
    overrides: [
      appClientProvider.overrideWithValue(client),
    ],
  );
}

void main() {
  group('HelperPolicyResolver.list', () {
    test('returns the items returned by app.helper_policies.list', () async {
      final fake = _FakeAppClient(
        listResponse: const PagedResult(
          items: <Map<String, dynamic>>[
            {
              'policy_id': 'baked-default',
              'allowed_helper_capabilities': ['shell'],
              'default_helper_capability': 'shell',
              'policy_source': 'baked_default',
            },
            {
              'policy_id': 'team-claude',
              'allowed_helper_capabilities': ['claude', 'shell'],
              'default_helper_capability': 'claude',
              'policy_source': 'repo_override',
            },
          ],
          cursorNext: null,
        ),
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final resolver = container.read(helperPolicyResolverProvider);
      final rows = await resolver.list();
      expect(rows, hasLength(2));
      expect(rows.first['policy_id'], 'baked-default');
      expect(rows.last['policy_source'], 'repo_override');
    });

    test('returns empty list when the daemon has no policies', () async {
      final fake = _FakeAppClient(
        listResponse: const PagedResult(
          items: <Map<String, dynamic>>[],
          cursorNext: null,
        ),
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final rows = await container.read(helperPolicyResolverProvider).list();
      expect(rows, isEmpty);
    });
  });

  group('HelperPolicyResolver.resolve', () {
    test(
        'passes projectId + override to daemon and parses snapshot from response',
        () async {
      final fake = _FakeAppClient(
        resolveResponse: <String, dynamic>{
          'resolved_policy': {
            'policy_id': 'team-claude',
            'allowed_helper_capabilities': ['claude', 'shell'],
            'default_helper_capability': 'claude',
            'policy_source': 'operator_override',
          },
          'snapshotted_at': '2026-05-25T12:00:00Z',
          'operator_override_of_policy_id': 'baked-default',
        },
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final snap = await container.read(helperPolicyResolverProvider).resolve(
            projectId: 'proj-1',
            operatorOverrideOfPolicyId: 'baked-default',
          );

      expect(fake.resolveCalls, hasLength(1));
      expect(fake.resolveCalls.single.projectId, 'proj-1');
      expect(
        fake.resolveCalls.single.operatorOverrideOfPolicyId,
        'baked-default',
      );

      expect(snap.resolvedPolicy.policyId, 'team-claude');
      expect(
        snap.resolvedPolicy.allowedHelperCapabilities,
        {'claude', 'shell'},
      );
      expect(snap.resolvedPolicy.defaultHelperCapability, 'claude');
      expect(snap.resolvedPolicy.policySource, PolicySource.operatorOverride);
      expect(snap.operatorOverrideOfPolicyId, 'baked-default');
    });

    test('omits operator_override_of_policy_id from the daemon call when null',
        () async {
      final fake = _FakeAppClient(
        resolveResponse: <String, dynamic>{
          'resolved_policy': {
            'policy_id': 'baked-default',
            'allowed_helper_capabilities': ['shell'],
            'default_helper_capability': 'shell',
            'policy_source': 'baked_default',
          },
          'snapshotted_at': '2026-05-25T12:00:00Z',
        },
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final snap = await container.read(helperPolicyResolverProvider).resolve(
            projectId: 'proj-1',
          );

      expect(fake.resolveCalls.single.operatorOverrideOfPolicyId, isNull);
      expect(snap.operatorOverrideOfPolicyId, isNull);
      expect(snap.resolvedPolicy.policySource, PolicySource.bakedDefault);
    });

    test(
        'fills in snapshotted_at locally when the daemon omits it (resolver convenience)',
        () async {
      final fake = _FakeAppClient(
        resolveResponse: <String, dynamic>{
          'resolved_policy': {
            'policy_id': 'baked-default',
            'allowed_helper_capabilities': ['shell'],
            'default_helper_capability': 'shell',
            'policy_source': 'baked_default',
          },
          // no snapshotted_at
        },
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final before = DateTime.now().toUtc();
      final snap = await container
          .read(helperPolicyResolverProvider)
          .resolve(projectId: 'proj-1');
      final after = DateTime.now().toUtc();

      // snapshottedAt must be a recent UTC time bracketed by the call.
      expect(snap.snapshottedAt.isUtc, isTrue);
      expect(
        snap.snapshottedAt
                .isAfter(before.subtract(const Duration(seconds: 1))) &&
            snap.snapshottedAt.isBefore(after.add(const Duration(seconds: 1))),
        isTrue,
        reason:
            'resolver should default snapshotted_at to ~now when daemon omits it',
      );
    });

    test('propagates daemon exceptions to the caller', () async {
      final fake = _FakeAppClient(
        resolveThrows: Exception('daemon exploded'),
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      await expectLater(
        container
            .read(helperPolicyResolverProvider)
            .resolve(projectId: 'proj-1'),
        throwsA(isA<Exception>()),
      );
    });
  });

  group(
      'HelperPolicyResolver.degradedSnapshot (FEAT-011 v1.0 absence fallback)',
      () {
    test(
        'produces a baked_default snapshot when daemon does not expose '
        'app.helper_policies.* (§6 absence fallback)', () {
      // No daemon calls needed: degradedSnapshot is purely client-side.
      final fake = _FakeAppClient();
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final snap =
          container.read(helperPolicyResolverProvider).degradedSnapshot();

      expect(
        snap.resolvedPolicy.policySource,
        PolicySource.bakedDefault,
        reason: 'fallback policy must be sourced as baked_default per §6',
      );
      expect(snap.resolvedPolicy.policyId, 'unset',
          reason:
              'caller-detectable sentinel — the contract requires "unset" so '
              'consumers can distinguish the degraded fallback from a real '
              'daemon-served baked default');
      expect(
        snap.resolvedPolicy.defaultHelperCapability,
        'shell',
      );
      expect(
        snap.resolvedPolicy.allowedHelperCapabilities,
        {'shell'},
      );
      expect(
        snap.resolvedPolicy.allowedHelperCapabilities
            .contains(snap.resolvedPolicy.defaultHelperCapability),
        isTrue,
        reason:
            'default ∈ allowed invariant (helper-policy.md §1) must hold even in fallback',
      );
      expect(snap.snapshottedAt.isUtc, isTrue);
      expect(snap.operatorOverrideOfPolicyId, isNull);
      expect(snap.repoOverridePath, isNull);
    });

    test('degradedSnapshot does NOT touch the daemon', () {
      final fake = _FakeAppClient();
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      container.read(helperPolicyResolverProvider).degradedSnapshot();
      expect(
        fake.resolveCalls,
        isEmpty,
        reason: 'degraded path is client-only; no daemon round-trip allowed',
      );
    });

    test(
        'degradedSnapshot is distinguishable from a daemon-supplied baked_default',
        () async {
      // A daemon-supplied baked_default returns its own (real) policy_id,
      // not the "unset" sentinel. This guarantees callers can detect
      // whether they're on the degraded path even though both carry
      // policySource == bakedDefault.
      final fake = _FakeAppClient(
        resolveResponse: <String, dynamic>{
          'resolved_policy': {
            'policy_id': 'baked-default',
            'allowed_helper_capabilities': ['shell'],
            'default_helper_capability': 'shell',
            'policy_source': 'baked_default',
          },
          'snapshotted_at': '2026-05-25T12:00:00Z',
        },
      );
      final container = _containerWith(fake);
      addTearDown(container.dispose);

      final daemonSnap = await container
          .read(helperPolicyResolverProvider)
          .resolve(projectId: 'proj-1');
      final degraded =
          container.read(helperPolicyResolverProvider).degradedSnapshot();

      expect(daemonSnap.resolvedPolicy.policySource,
          degraded.resolvedPolicy.policySource);
      expect(
        daemonSnap.resolvedPolicy.policyId == degraded.resolvedPolicy.policyId,
        isFalse,
        reason:
            'policy_id sentinel "unset" lets callers detect the §6 fallback',
      );
    });
  });
}
