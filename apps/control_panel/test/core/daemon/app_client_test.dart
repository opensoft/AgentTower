import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [AppClient] argument validation that does NOT need a
/// real daemon round-trip. Review fix H6 / test lane.
void main() {
  group('AppClient.sendInput', () {
    test('rejects empty payload before issuing any wire call', () async {
      // Build with a never-connecting socket so the test fails loudly if
      // the guard ever lets an invalid call through to the network layer.
      final client = AppClient(
        session: DaemonSession(
          client: SocketClient('/nonexistent/path/never-bound.sock'),
        ),
      );
      expect(
        () => client.sendInput(targetAgentId: 'agent-1', payload: const {}),
        throwsArgumentError,
      );
    });

    test('rejects an empty payload object (not just null)', () async {
      final client = AppClient(
        session: DaemonSession(
          client: SocketClient('/nonexistent/path/never-bound.sock'),
        ),
      );
      expect(
        () => client.sendInput(
          targetAgentId: 'agent-1',
          payload: const <String, Object>{},
        ),
        throwsArgumentError,
      );
    });
  });
}
