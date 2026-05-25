import 'package:agenttower_control_panel/domain/lifecycles/handoff_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [HandoffStateValidator]. Spec FR-044 + FR-042/FR-081
/// (supersede semantics).
///
/// Allowed transitions per the validator source:
///   drafted    → submitted
///   submitted  → accepted | cancelled | superseded
///   accepted   → active | cancelled | superseded
///   active     → waiting | blocked | completed | cancelled | superseded
///   waiting    → active
///   blocked    → active
///   completed | cancelled | superseded — terminal (no outgoing)
///
/// Per FR-081, supersede is a record-only intent change but the state
/// transition itself IS allowed from submitted/accepted/active.
void main() {
  // Hand-written transition table mirroring the validator source so
  // tests fail loudly if the source diverges.
  final allowed = <AssignmentState, Set<AssignmentState>>{
    AssignmentState.drafted: {AssignmentState.submitted},
    AssignmentState.submitted: {
      AssignmentState.accepted,
      AssignmentState.cancelled,
      AssignmentState.superseded,
    },
    AssignmentState.accepted: {
      AssignmentState.active,
      AssignmentState.cancelled,
      AssignmentState.superseded,
    },
    AssignmentState.active: {
      AssignmentState.waiting,
      AssignmentState.blocked,
      AssignmentState.completed,
      AssignmentState.cancelled,
      AssignmentState.superseded,
    },
    AssignmentState.waiting: {AssignmentState.active},
    AssignmentState.blocked: {AssignmentState.active},
    AssignmentState.completed: <AssignmentState>{},
    AssignmentState.cancelled: <AssignmentState>{},
    AssignmentState.superseded: <AssignmentState>{},
  };

  const terminals = {
    AssignmentState.completed,
    AssignmentState.cancelled,
    AssignmentState.superseded,
  };

  group('HandoffStateValidator.isValidTransition — allowed', () {
    test('self-transitions are always valid (no-op)', () {
      for (final s in AssignmentState.values) {
        expect(
          HandoffStateValidator.isValidTransition(s, s),
          isTrue,
          reason: 'self-transition $s → $s should be valid',
        );
      }
    });

    test('every documented allowed transition is accepted', () {
      allowed.forEach((from, tos) {
        for (final to in tos) {
          expect(
            HandoffStateValidator.isValidTransition(from, to),
            isTrue,
            reason: '$from → $to should be allowed per FR-044',
          );
        }
      });
    });

    test('supersede is allowed from submitted/accepted/active (FR-081)', () {
      for (final from in const [
        AssignmentState.submitted,
        AssignmentState.accepted,
        AssignmentState.active,
      ]) {
        expect(
          HandoffStateValidator.isValidTransition(
            from,
            AssignmentState.superseded,
          ),
          isTrue,
          reason: '$from → superseded must be allowed per FR-081',
        );
      }
    });
  });

  group('HandoffStateValidator.isValidTransition — rejected', () {
    test('every transition NOT in the allowed table is rejected', () {
      for (final from in AssignmentState.values) {
        for (final to in AssignmentState.values) {
          if (from == to) continue;
          final shouldAllow = allowed[from]!.contains(to);
          expect(
            HandoffStateValidator.isValidTransition(from, to),
            shouldAllow,
            reason: '$from → $to expected ${shouldAllow ? "allow" : "reject"}',
          );
        }
      }
    });

    test('drafted may NOT short-circuit to cancelled or superseded', () {
      expect(
        HandoffStateValidator.isValidTransition(
          AssignmentState.drafted,
          AssignmentState.cancelled,
        ),
        isFalse,
        reason: 'a draft is discarded client-side without a state transition',
      );
      expect(
        HandoffStateValidator.isValidTransition(
          AssignmentState.drafted,
          AssignmentState.superseded,
        ),
        isFalse,
      );
    });

    test(
        'waiting and blocked may NOT short-circuit to cancelled or superseded '
        '(must return to active first)', () {
      for (final from in const [
        AssignmentState.waiting,
        AssignmentState.blocked,
      ]) {
        expect(
          HandoffStateValidator.isValidTransition(
            from,
            AssignmentState.cancelled,
          ),
          isFalse,
          reason: '$from must return to active before terminating',
        );
        expect(
          HandoffStateValidator.isValidTransition(
            from,
            AssignmentState.superseded,
          ),
          isFalse,
          reason: '$from must return to active before being superseded',
        );
        expect(
          HandoffStateValidator.isValidTransition(
            from,
            AssignmentState.completed,
          ),
          isFalse,
          reason: '$from must return to active before completing',
        );
      }
    });

    test('terminal states reject every non-self outgoing transition', () {
      for (final from in terminals) {
        for (final to in AssignmentState.values) {
          if (from == to) continue;
          expect(
            HandoffStateValidator.isValidTransition(from, to),
            isFalse,
            reason: 'terminal $from must not transition to $to',
          );
        }
      }
    });
  });

  group('HandoffStateValidator.isTerminal', () {
    test('terminal classification matches FR-044 terminal set', () {
      for (final s in AssignmentState.values) {
        expect(
          HandoffStateValidator.isTerminal(s),
          terminals.contains(s),
          reason: 'terminal classification mismatch for $s',
        );
      }
    });
  });
}
