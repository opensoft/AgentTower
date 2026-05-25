import 'package:agenttower_control_panel/domain/lifecycles/pane_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [PaneStateValidator]. Spec FR-014 + data-model §1.4.
///
/// Allowed transitions enumerated here:
/// - `discoveredAndUnmanaged ↔ discoveredAndRegistered` (adoption / de-adoption)
/// - Any state ↔ `inactiveOrStale`
/// - Any state ↔ `discoveryDegraded`
/// - Self-transitions (no-op) are always valid.
/// - There are NO terminal pane states.
void main() {
  group('PaneStateValidator.isValidTransition', () {
    test('every self-transition is valid (no-op)', () {
      for (final s in PaneState.values) {
        expect(
          PaneStateValidator.isValidTransition(s, s),
          isTrue,
          reason: 'self-transition $s → $s should be valid',
        );
      }
    });

    test('adoption swap discoveredAndUnmanaged ↔ discoveredAndRegistered', () {
      expect(
        PaneStateValidator.isValidTransition(
          PaneState.discoveredAndUnmanaged,
          PaneState.discoveredAndRegistered,
        ),
        isTrue,
      );
      expect(
        PaneStateValidator.isValidTransition(
          PaneState.discoveredAndRegistered,
          PaneState.discoveredAndUnmanaged,
        ),
        isTrue,
      );
    });

    test('any state may transition to inactiveOrStale and back', () {
      for (final s in PaneState.values) {
        expect(
          PaneStateValidator.isValidTransition(s, PaneState.inactiveOrStale),
          isTrue,
          reason: '$s → inactiveOrStale must be valid',
        );
        expect(
          PaneStateValidator.isValidTransition(PaneState.inactiveOrStale, s),
          isTrue,
          reason: 'inactiveOrStale → $s must be valid',
        );
      }
    });

    test('any state may transition to discoveryDegraded and back', () {
      for (final s in PaneState.values) {
        expect(
          PaneStateValidator.isValidTransition(s, PaneState.discoveryDegraded),
          isTrue,
          reason: '$s → discoveryDegraded must be valid',
        );
        expect(
          PaneStateValidator.isValidTransition(PaneState.discoveryDegraded, s),
          isTrue,
          reason: 'discoveryDegraded → $s must be valid',
        );
      }
    });

    // FR-014 has no "rejected" transitions among the four states because the
    // two orthogonal states (inactive/stale, discovery-degraded) are
    // bidirectionally reachable from anywhere. With those swept up by the
    // tests above and the adoption swap covered, the only remaining pair-set
    // is { discoveredAndUnmanaged, discoveredAndRegistered } both ways —
    // already validated. So `isValidTransition` accepts EVERY pair. We
    // assert that explicitly so any future regression that introduces a
    // rejection accidentally is caught.
    test('all 16 ordered pairs are valid (no rejections exist at MVP)', () {
      for (final from in PaneState.values) {
        for (final to in PaneState.values) {
          expect(
            PaneStateValidator.isValidTransition(from, to),
            isTrue,
            reason: 'pair $from → $to should be valid per FR-014',
          );
        }
      }
    });
  });

  group('PaneStateValidator.isTerminal', () {
    test('no pane state is terminal per FR-014', () {
      for (final s in PaneState.values) {
        expect(
          PaneStateValidator.isTerminal(s),
          isFalse,
          reason: '$s must not be terminal',
        );
      }
    });
  });
}
