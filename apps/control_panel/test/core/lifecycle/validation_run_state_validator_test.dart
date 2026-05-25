import 'package:agenttower_control_panel/domain/lifecycles/validation_run_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [ValidationRunStateValidator]. Spec FR-048.
///
/// Allowed transitions:
///   queued → running → completed
///   queued | running → cancelled
///   queued → failed_to_start
///   completed | cancelled | failed_to_start — terminal
///
/// `result` is only meaningful in terminal states.
void main() {
  final allowed = <RunState, Set<RunState>>{
    RunState.queued: {
      RunState.running,
      RunState.cancelled,
      RunState.failedToStart,
    },
    RunState.running: {
      RunState.completed,
      RunState.cancelled,
    },
    RunState.completed: <RunState>{},
    RunState.cancelled: <RunState>{},
    RunState.failedToStart: <RunState>{},
  };

  const terminals = {
    RunState.completed,
    RunState.cancelled,
    RunState.failedToStart,
  };

  group('ValidationRunStateValidator.isValidTransition — allowed', () {
    test('self-transitions are valid for every state', () {
      for (final s in RunState.values) {
        expect(
          ValidationRunStateValidator.isValidTransition(s, s),
          isTrue,
          reason: 'self-transition $s → $s should be valid',
        );
      }
    });

    test('every documented allowed transition is accepted', () {
      allowed.forEach((from, tos) {
        for (final to in tos) {
          expect(
            ValidationRunStateValidator.isValidTransition(from, to),
            isTrue,
            reason: '$from → $to should be allowed per FR-048',
          );
        }
      });
    });
  });

  group('ValidationRunStateValidator.isValidTransition — rejected', () {
    test('every transition NOT in the allowed table is rejected', () {
      for (final from in RunState.values) {
        for (final to in RunState.values) {
          if (from == to) continue;
          final shouldAllow = allowed[from]!.contains(to);
          expect(
            ValidationRunStateValidator.isValidTransition(from, to),
            shouldAllow,
            reason: '$from → $to expected ${shouldAllow ? "allow" : "reject"}',
          );
        }
      }
    });

    test('failedToStart is reachable only from queued', () {
      for (final from in RunState.values) {
        if (from == RunState.queued) continue;
        if (from == RunState.failedToStart) continue; // self
        expect(
          ValidationRunStateValidator.isValidTransition(
            from,
            RunState.failedToStart,
          ),
          isFalse,
          reason: '$from → failedToStart must be rejected',
        );
      }
    });

    test('running may not skip back to queued', () {
      expect(
        ValidationRunStateValidator.isValidTransition(
          RunState.running,
          RunState.queued,
        ),
        isFalse,
      );
    });

    test('queued may not skip directly to completed', () {
      expect(
        ValidationRunStateValidator.isValidTransition(
          RunState.queued,
          RunState.completed,
        ),
        isFalse,
        reason: 'queued must transition through running first',
      );
    });

    test('terminal states reject every non-self outgoing transition', () {
      for (final from in terminals) {
        for (final to in RunState.values) {
          if (from == to) continue;
          expect(
            ValidationRunStateValidator.isValidTransition(from, to),
            isFalse,
            reason: 'terminal $from must not transition to $to',
          );
        }
      }
    });
  });

  group('ValidationRunStateValidator.isTerminal', () {
    test('terminal classification matches FR-048 terminal set', () {
      for (final s in RunState.values) {
        expect(
          ValidationRunStateValidator.isTerminal(s),
          terminals.contains(s),
          reason: 'terminal classification mismatch for $s',
        );
      }
    });
  });

  group('ValidationRunStateValidator.isResultMeaningful', () {
    test('result is meaningful only in terminal states', () {
      for (final s in RunState.values) {
        expect(
          ValidationRunStateValidator.isResultMeaningful(s),
          terminals.contains(s),
          reason: 'isResultMeaningful must be true iff $s is terminal (FR-048)',
        );
      }
    });
  });
}
