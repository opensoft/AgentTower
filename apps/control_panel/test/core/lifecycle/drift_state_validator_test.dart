import 'package:agenttower_control_panel/domain/lifecycles/drift_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [DriftStateValidator]. Spec FR-034 + data-model §1.9.
///
/// Canonical forward path:
///   new → review_needed → confirmed → repair_planned → resolved
///
/// Terminal states: resolved, acceptedAsBuilt, dismissed.
/// Any non-terminal state may also transition to acceptedAsBuilt or
/// dismissed. Forward states may not be skipped except into the terminal
/// pair.
void main() {
  const forwardPath = [
    DriftStatus.newFinding,
    DriftStatus.reviewNeeded,
    DriftStatus.confirmed,
    DriftStatus.repairPlanned,
    DriftStatus.resolved,
  ];
  const terminals = {
    DriftStatus.resolved,
    DriftStatus.acceptedAsBuilt,
    DriftStatus.dismissed,
  };
  final nonTerminals =
      DriftStatus.values.where((s) => !terminals.contains(s)).toList();

  group('DriftStateValidator.isValidTransition — allowed', () {
    test('self-transitions are valid for every state', () {
      for (final s in DriftStatus.values) {
        expect(
          DriftStateValidator.isValidTransition(s, s),
          isTrue,
          reason: 'self-transition $s → $s should be valid',
        );
      }
    });

    test('canonical forward path: each step n → n+1 is valid', () {
      for (var i = 0; i < forwardPath.length - 1; i++) {
        final from = forwardPath[i];
        final to = forwardPath[i + 1];
        expect(
          DriftStateValidator.isValidTransition(from, to),
          isTrue,
          reason: 'forward $from → $to must be valid',
        );
      }
    });

    test('any non-terminal → acceptedAsBuilt is valid', () {
      for (final from in nonTerminals) {
        expect(
          DriftStateValidator.isValidTransition(
            from,
            DriftStatus.acceptedAsBuilt,
          ),
          isTrue,
          reason: '$from → acceptedAsBuilt must be valid',
        );
      }
    });

    test('any non-terminal → dismissed is valid', () {
      for (final from in nonTerminals) {
        expect(
          DriftStateValidator.isValidTransition(from, DriftStatus.dismissed),
          isTrue,
          reason: '$from → dismissed must be valid',
        );
      }
    });
  });

  group('DriftStateValidator.isValidTransition — rejected', () {
    test('every terminal state rejects every non-self outgoing transition', () {
      for (final from in terminals) {
        for (final to in DriftStatus.values) {
          if (from == to) continue;
          expect(
            DriftStateValidator.isValidTransition(from, to),
            isFalse,
            reason: 'terminal $from must not transition to $to',
          );
        }
      }
    });

    test('forward path may not skip forward (except into terminal pair)', () {
      // For each non-terminal source on the forward path, the only valid
      // forward path target is the immediately-next state. Any later
      // forward-path state (except acceptedAsBuilt/dismissed which are
      // tested above as allowed) MUST be rejected.
      for (var i = 0; i < forwardPath.length - 1; i++) {
        final from = forwardPath[i];
        for (var j = 0; j < forwardPath.length; j++) {
          if (j == i || j == i + 1) continue;
          final to = forwardPath[j];
          // Skip the case where `to` is a terminal — covered separately.
          if (to == DriftStatus.resolved && j > i + 1) {
            // resolved is terminal but reachable only via the i==fromIdx,
            // j==i+1 case (i.e. only from repairPlanned). Anything else
            // must be rejected.
            expect(
              DriftStateValidator.isValidTransition(from, to),
              isFalse,
              reason:
                  '$from must not skip directly to resolved (only repairPlanned → resolved is allowed)',
            );
            continue;
          }
          expect(
            DriftStateValidator.isValidTransition(from, to),
            isFalse,
            reason: '$from must not skip forward to $to',
          );
        }
      }
    });

    test('backward transitions on the canonical path are rejected', () {
      for (var i = 1; i < forwardPath.length; i++) {
        for (var j = 0; j < i; j++) {
          final from = forwardPath[i];
          final to = forwardPath[j];
          expect(
            DriftStateValidator.isValidTransition(from, to),
            isFalse,
            reason: 'backward $from → $to must be rejected',
          );
        }
      }
    });

    test('acceptedAsBuilt and dismissed do not transition into each other', () {
      expect(
        DriftStateValidator.isValidTransition(
          DriftStatus.acceptedAsBuilt,
          DriftStatus.dismissed,
        ),
        isFalse,
      );
      expect(
        DriftStateValidator.isValidTransition(
          DriftStatus.dismissed,
          DriftStatus.acceptedAsBuilt,
        ),
        isFalse,
      );
    });
  });

  group('DriftStateValidator.isTerminal', () {
    test('terminal states match the FR-034 terminal set', () {
      for (final s in DriftStatus.values) {
        expect(
          DriftStateValidator.isTerminal(s),
          terminals.contains(s),
          reason: 'terminal classification mismatch for $s',
        );
      }
    });
  });
}
