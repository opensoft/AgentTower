import 'package:agenttower_control_panel/core/daemon/errors.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/mock_daemon_client.dart';

/// FR-002 contract-version-skew end-to-end. T056 (Phase 3 US1) +
/// spec-quality-pass F1 (US1 acceptance scenario added by spec edit).
///
/// Drives the mock daemon's `_use_helper:
/// app_contract_major_unsupported` path and asserts the FR-036
/// failure envelope is parsed into the canonical
/// [AppContractErrorCode.appContractMajorUnsupported].
///
/// In a full end-to-end driver this test would also assert:
///   - global banner becomes visible
///   - every US1 mutation surface disables its primary action
///   - tooltip text on the disabled action cites
///     "contract-version-incompatible" from FR-004
/// The widget-level assertions land in Phase 9 once the polish pass
/// agrees on banner/disabled-affordance copy.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  test('app.hello with major skew surfaces appContractMajorUnsupported',
      () async {
    final harness = await MockDaemonClient.start(fixture: {
      'app_contract_version': '2.0',
      'daemon_version': '2.0.0-mock',
      'responses': {
        'app.hello': {
          'ok': false,
          '_use_helper': 'app_contract_major_unsupported',
        },
      },
    });
    addTearDown(harness.stop);

    final client = SocketClient(harness.socketPath);
    final session = DaemonSession(client: client);

    Object? thrown;
    try {
      await session.bootstrap();
    } catch (e) {
      thrown = e;
    }

    expect(thrown, isA<AppContractError>());
    final err = thrown! as AppContractError;
    expect(err.code, AppContractErrorCode.appContractMajorUnsupported);
    expect(err.details['daemon_app_contract_version'], '2.0');
    expect(err.details['client_app_contract_major'], 1);

    await session.dispose();
  });
}
