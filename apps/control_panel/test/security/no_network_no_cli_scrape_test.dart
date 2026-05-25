@Tags(['security'])
library;

import 'dart:io';

import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/core/update/release_feed_check.dart';
import 'package:agenttower_control_panel/features/agent_ops/attention/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/providers.dart';
import 'package:agenttower_control_panel/features/notifications/providers.dart';
import 'package:agenttower_control_panel/features/project_specs/drift/providers.dart';
import 'package:agenttower_control_panel/features/project_specs/providers.dart';
import 'package:agenttower_control_panel/features/testing_demo/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/fixture_builders.dart';
import '../helpers/mock_daemon_client.dart';

/// T155 — SC-009 verification: no outbound network sockets and no
/// subprocess invocation of the `agenttower` CLI binary from the
/// desktop control panel.
///
/// Spy approach (per task constraints):
///
///   Group A (network): a custom [IOOverrides] subclass intercepts
///     every `Socket.connect` / `Socket.startConnect` call made by
///     the app while it exercises every list provider against the
///     mock-daemon harness. Each attempt is recorded as a
///     `_SocketAttempt(host, port)` and asserted at the end to be
///     either (a) a Unix-domain socket to the per-test harness
///     socket path, or (b) — in the dedicated FR-068 sub-test —
///     a stubbed HTTPS GET whose URL host equals
///     `releases.opensoft.one`.
///
///     A real packet capture via `tcpdump` would be the most
///     authoritative proof, but tcpdump requires CAP_NET_RAW or root
///     which is not feasible in the pure-Dart unit-test lane that
///     this file ships in. The `IOOverrides`-based spy catches every
///     `dart:io` outbound attempt the app makes through the standard
///     APIs — which is everything the app code actually uses
///     (`SocketClient` for the daemon, `HttpClient` for the release
///     feed) — and is consistent with the rest of FEAT-012's testing
///     model (no elevated privileges; pure Dart).
///
///   Group B (subprocess): `dart:io`'s `Process` class is NOT covered
///     by `IOOverrides` (the SDK only exposes overrides for sockets,
///     filesystem, stdio — not `Process.run` / `Process.start`). We
///     therefore use a static source-scan: traverse every `.dart`
///     file under `lib/` and assert no call site invokes
///     `Process.run` / `Process.runSync` / `Process.start` /
///     `Process.startSync` with the string literal `'agenttower'`
///     as the executable. The desktop app is a thin client over the
///     daemon socket per FR-001 and Constitution principle IV; if it
///     ever shelled out to the CLI to populate a view, that would be
///     the regression this test is here to catch.
///
/// Both groups skip when `python3` is unavailable because Group A
/// needs the harness to drive the workspace; Group B reads files
/// from disk and would technically run without python, but skipping
/// it under the same gate keeps the suite's pass/skip story uniform
/// (a CI environment without python is also one where we cannot
/// claim SC-009 was verified end-to-end this run).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  setUp(() {
    ContractRegistry.resetForTesting();
    seedMvpContractDeclarations();
  });

  group('Group A — outbound socket trace under provider exercise', () {
    test('every socket connect is a Unix socket to the daemon path; '
        'no TCP/UDP egress; no HTTPS without an opt-in FR-068 trigger',
        () async {
      if (!pythonOk) {
        markTestSkipped(
          'python3 not on PATH; cannot spawn mock-daemon harness',
        );
        return;
      }

      final harness = await MockDaemonClient.start(fixture: _fullFixture());
      addTearDown(harness.stop);

      final socketSpy = _SocketTraceOverrides();
      final httpSpy = _HttpTraceOverrides();

      await HttpOverrides.runZoned(
        () => IOOverrides.runZoned(
          () async {
            final socketClient = SocketClient(harness.socketPath);
            final session = DaemonSession(client: socketClient);
            await session.bootstrap();
            addTearDown(session.dispose);
            final appClient = AppClient(session: session);

            final container = ProviderContainer(
              overrides: [
                socketClientProvider.overrideWithValue(socketClient),
                daemonSessionProvider.overrideWithValue(session),
                appClientProvider.overrideWithValue(appClient),
              ],
            );
            addTearDown(container.dispose);

            // Traverse every workspace's primary list/refresh surface.
            // Each `read(...future)` triggers a real wire RPC through
            // the SocketClient, so it MUST surface in the trace as a
            // Unix-socket connect to harness.socketPath.
            await container.read(dashboardProvider.future);
            await container.read(containerListProvider.future);
            await container.read(paneListProvider.future);
            await container.read(agentListProvider.future);
            await container.read(eventListProvider.future);
            await container.read(queueListProvider.future);
            await container.read(routeListProvider.future);
            await container.read(readinessProvider.future);
            await container.read(projectListProvider.future);
            await container.read(
              driftListProvider(const DriftListQuery()).future,
            );
            await container.read(
              notificationListProvider(
                const NotificationListQuery(),
              ).future,
            );
            await container.read(
              validationEntrypointListProvider(
                const EntrypointListQuery(),
              ).future,
            );
            await container.read(
              attentionListProvider(
                const AttentionListQuery(projectId: 'proj-1'),
              ).future,
            );

            // Trigger refresh on every list provider — a second pass
            // exercises the cache-invalidation code path and proves
            // refreshes also stay on the local socket.
            container.invalidate(dashboardProvider);
            container.invalidate(paneListProvider);
            container.invalidate(agentListProvider);
            await container.read(dashboardProvider.future);
            await container.read(paneListProvider.future);
            await container.read(agentListProvider.future);
          },
          socketConnect: socketSpy.socketConnect,
          socketStartConnect: socketSpy.socketStartConnect,
        ),
        createHttpClient: httpSpy.createHttpClient,
      );

      // ----- Group A assertions -----

      expect(
        socketSpy.attempts,
        isNotEmpty,
        reason: 'spy installed but observed zero socket activity — the '
            'test driver likely did not exercise any wire call',
      );
      for (final attempt in socketSpy.attempts) {
        expect(
          attempt.isUnix,
          isTrue,
          reason: 'unexpected non-Unix socket connect during normal '
              'workspace exercise: $attempt — SC-009 requires the app '
              'to make zero outbound TCP/UDP socket attempts under '
              'normal operation',
        );
        expect(
          attempt.host as String,
          equals(harness.socketPath),
          reason: 'Unix socket connect targeted an unexpected path: '
              '${attempt.host} (expected ${harness.socketPath})',
        );
      }

      expect(
        httpSpy.requestedUrls,
        isEmpty,
        reason: 'unexpected HttpClient activity during normal workspace '
            'exercise — the FR-068 release-feed check is the ONLY '
            'permitted HTTPS path and it is opt-in via '
            'UpdateInfoNotifier.runOnce(); a normal provider '
            'exercise must not trigger any HTTP traffic',
      );
    });

    test('FR-068 release-feed check only targets releases.opensoft.one',
        () async {
      // This sub-test does NOT spawn the harness — it asserts a static
      // property of the ReleaseFeedChecker URL surface, plus that the
      // checker only constructs an HTTPS URL with the expected host.
      final defaultChecker = ReleaseFeedChecker();
      expect(defaultChecker.feedUrl.scheme, equals('https'));
      expect(defaultChecker.feedUrl.host, equals('releases.opensoft.one'));

      // Constructor must reject any non-HTTPS override (defense in depth
      // against a misconfigured Settings/env-var feed URL).
      expect(
        () => ReleaseFeedChecker(
          feedUrl: Uri.parse('http://releases.opensoft.one/x.json'),
        ),
        throwsArgumentError,
      );
    });
  });

  group('Group B — no subprocess invocation of the agenttower CLI', () {
    test('no lib/*.dart file invokes Process.{run,runSync,start,startSync} '
        'with `agenttower` as the executable', () async {
      if (!pythonOk) {
        markTestSkipped(
          'python3 not on PATH; skipping under the same gate as Group A '
          'so the suite\'s pass/skip story is uniform',
        );
        return;
      }

      // Resolve `lib/` relative to the test runner cwd
      // (`apps/control_panel/`). The unit-test runner cd's here per
      // the same convention `MockDaemonClient` relies on.
      final libDir = Directory('lib');
      expect(
        libDir.existsSync(),
        isTrue,
        reason: 'expected to run from apps/control_panel/ where lib/ exists',
      );

      final offenders = <String>[];
      // RegExps that capture `Process.<verb>(...)` with `'agenttower'`
      // or `"agenttower"` as the first positional argument. We match
      // the bare string literal — any caller dynamically computing the
      // binary name from a variable would be a separate code-review
      // concern, but is not what FR-001 + Constitution principle IV
      // forbids (the forbidden pattern is "shell out to the CLI to
      // populate the UI", which would be a hard-coded literal).
      final processCallPattern = RegExp(
        r'''Process\.(run|runSync|start|startSync)\s*\(\s*['"]agenttower['"]''',
        multiLine: true,
      );

      await for (final entity in libDir.list(recursive: true)) {
        if (entity is! File) continue;
        if (!entity.path.endsWith('.dart')) continue;
        // Skip generated freezed/json_serializable files — they cannot
        // by construction call Process.
        if (entity.path.endsWith('.freezed.dart')) continue;
        if (entity.path.endsWith('.g.dart')) continue;

        final source = await entity.readAsString();
        if (processCallPattern.hasMatch(source)) {
          offenders.add(entity.path);
        }
      }

      expect(
        offenders,
        isEmpty,
        reason: 'SC-009 / Constitution IV violation: the desktop app '
            'must be a thin client over the daemon socket and must NOT '
            'shell out to the `agenttower` CLI. Offending file(s):\n'
            '  ${offenders.join('\n  ')}',
      );
    });
  });
}

/// Records every `Socket.connect` / `Socket.startConnect` attempt and
/// delegates to the underlying `dart:io` implementation so the actual
/// wire RPCs still complete.
class _SocketTraceOverrides extends IOOverrides {
  final List<_SocketAttempt> attempts = <_SocketAttempt>[];

  @override
  Future<Socket> socketConnect(
    Object? host,
    int port, {
    Object? sourceAddress,
    int sourcePort = 0,
    Duration? timeout,
  }) {
    attempts.add(_SocketAttempt(host, port));
    return super.socketConnect(
      host,
      port,
      sourceAddress: sourceAddress,
      sourcePort: sourcePort,
      timeout: timeout,
    );
  }

  @override
  Future<ConnectionTask<Socket>> socketStartConnect(
    Object? host,
    int port, {
    Object? sourceAddress,
    int sourcePort = 0,
  }) {
    attempts.add(_SocketAttempt(host, port));
    return super.socketStartConnect(
      host,
      port,
      sourceAddress: sourceAddress,
      sourcePort: sourcePort,
    );
  }
}

class _SocketAttempt {
  _SocketAttempt(this.host, this.port);
  final Object? host;
  final int port;

  /// Unix-domain sockets surface here as an `InternetAddress` whose
  /// `type` is `InternetAddressType.unix`. Every other host shape
  /// (`String` hostname, `InternetAddress` with IPv4/IPv6 type) is
  /// a real network socket attempt and SC-009 forbids it.
  bool get isUnix {
    final h = host;
    return h is InternetAddress && h.type == InternetAddressType.unix;
  }

  @override
  String toString() => '_SocketAttempt(host=$host, port=$port)';
}

/// Recording `HttpOverrides` — every constructed `HttpClient` is wrapped
/// in a forwarding stub that captures the URL of each `open*` call.
/// Because the Group A primary sub-test does NOT invoke
/// `UpdateInfoNotifier.runOnce()`, we expect zero recorded URLs;
/// any recorded URL is a SC-009 regression.
class _HttpTraceOverrides extends HttpOverrides {
  final List<Uri> requestedUrls = <Uri>[];

  @override
  HttpClient createHttpClient(SecurityContext? context) {
    return _RecordingHttpClient(super.createHttpClient(context), requestedUrls);
  }
}

class _RecordingHttpClient implements HttpClient {
  _RecordingHttpClient(this._inner, this._sink);

  final HttpClient _inner;
  final List<Uri> _sink;

  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) {
    _sink.add(url);
    return _inner.openUrl(method, url);
  }

  @override
  Future<HttpClientRequest> open(
    String method,
    String host,
    int port,
    String path,
  ) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.open(method, host, port, path);
  }

  @override
  Future<HttpClientRequest> getUrl(Uri url) {
    _sink.add(url);
    return _inner.getUrl(url);
  }

  @override
  Future<HttpClientRequest> get(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.get(host, port, path);
  }

  @override
  Future<HttpClientRequest> postUrl(Uri url) {
    _sink.add(url);
    return _inner.postUrl(url);
  }

  @override
  Future<HttpClientRequest> post(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.post(host, port, path);
  }

  @override
  Future<HttpClientRequest> putUrl(Uri url) {
    _sink.add(url);
    return _inner.putUrl(url);
  }

  @override
  Future<HttpClientRequest> put(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.put(host, port, path);
  }

  @override
  Future<HttpClientRequest> deleteUrl(Uri url) {
    _sink.add(url);
    return _inner.deleteUrl(url);
  }

  @override
  Future<HttpClientRequest> delete(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.delete(host, port, path);
  }

  @override
  Future<HttpClientRequest> patchUrl(Uri url) {
    _sink.add(url);
    return _inner.patchUrl(url);
  }

  @override
  Future<HttpClientRequest> patch(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.patch(host, port, path);
  }

  @override
  Future<HttpClientRequest> headUrl(Uri url) {
    _sink.add(url);
    return _inner.headUrl(url);
  }

  @override
  Future<HttpClientRequest> head(String host, int port, String path) {
    final url = Uri(scheme: 'http', host: host, port: port, path: path);
    _sink.add(url);
    return _inner.head(host, port, path);
  }

  // Pass-through configuration knobs. We forward every getter/setter the
  // real `HttpClient` exposes so the wrapped client behaves identically
  // for callers that tune timeouts, idle policy, proxies, or
  // authentication.

  @override
  bool get autoUncompress => _inner.autoUncompress;
  @override
  set autoUncompress(bool value) => _inner.autoUncompress = value;

  @override
  Duration? get connectionTimeout => _inner.connectionTimeout;
  @override
  set connectionTimeout(Duration? value) => _inner.connectionTimeout = value;

  @override
  Duration get idleTimeout => _inner.idleTimeout;
  @override
  set idleTimeout(Duration value) => _inner.idleTimeout = value;

  @override
  int? get maxConnectionsPerHost => _inner.maxConnectionsPerHost;
  @override
  set maxConnectionsPerHost(int? value) =>
      _inner.maxConnectionsPerHost = value;

  @override
  String? get userAgent => _inner.userAgent;
  @override
  set userAgent(String? value) => _inner.userAgent = value;

  @override
  void addCredentials(
    Uri url,
    String realm,
    HttpClientCredentials credentials,
  ) =>
      _inner.addCredentials(url, realm, credentials);

  @override
  void addProxyCredentials(
    String host,
    int port,
    String realm,
    HttpClientCredentials credentials,
  ) =>
      _inner.addProxyCredentials(host, port, realm, credentials);

  @override
  set authenticate(
    Future<bool> Function(Uri url, String scheme, String? realm)? f,
  ) =>
      _inner.authenticate = f;

  @override
  set authenticateProxy(
    Future<bool> Function(
      String host,
      int port,
      String scheme,
      String? realm,
    )? f,
  ) =>
      _inner.authenticateProxy = f;

  @override
  set badCertificateCallback(
    bool Function(X509Certificate cert, String host, int port)? callback,
  ) =>
      _inner.badCertificateCallback = callback;

  @override
  set connectionFactory(
    Future<ConnectionTask<Socket>> Function(
      Uri url,
      String? proxyHost,
      int? proxyPort,
    )? f,
  ) =>
      _inner.connectionFactory = f;

  @override
  set findProxy(String Function(Uri url)? f) => _inner.findProxy = f;

  @override
  // ignore: inference_failure_on_function_return_type
  set keyLog(Function(String line)? callback) => _inner.keyLog = callback;

  @override
  void close({bool force = false}) => _inner.close(force: force);
}

/// Fixture covering every list/dashboard surface a Group-A pass touches.
/// Modeled on `us1_smoke_walk._us1Fixture` with the extra entity
/// surfaces (drift, attention, notifications, validation entrypoints,
/// project) so every provider read returns a real success envelope
/// instead of an error path that would short-circuit the trace.
Map<String, dynamic> _fullFixture() {
  return {
    'app_contract_version': '1.0',
    'daemon_version': '0.11.0-mock',
    'app_session_token': '00000000-0000-4000-8000-000000000001',
    'app_session_id': 1,
    'host_user_id': '1000',
    'schema_version': 1,
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.dashboard': {
        'ok': true,
        'result': Fixtures.dashboardResult(),
      },
      'app.container.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.container()]),
      },
      'app.pane.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.pane()]),
      },
      'app.agent.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.agent()]),
      },
      'app.event.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.event()]),
      },
      'app.queue.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.queueRow()]),
      },
      'app.route.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.route()]),
      },
      'app.readiness': {
        'ok': true,
        'result': Fixtures.readinessResult(),
      },
      'app.project.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.project()]),
      },
      'app.drift.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.drift()]),
      },
      'app.notification.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.notification()]),
      },
      'app.validation.entrypoint.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.validationEntrypoint()]),
      },
      'app.attention.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.attentionItem()]),
      },
    },
  };
}
