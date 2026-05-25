import 'package:agenttower_control_panel/domain/lifecycles/feature_change_stage_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [FeatureChangeStageValidator]. Spec FR-028 + F7-b.
///
/// At MVP the only operator-driven stage transition the app may trigger
/// is the un-defer action:
/// - `deferred → definition` is allowed
/// - `deferred → spec_ready` is allowed
/// - Any other operator-driven transition is rejected (those are daemon-
///   driven and out of scope for this validator).
///
/// `deferred` is NON-terminal per F7-b. Only `merged` is operator-terminal.
void main() {
  group('FeatureChangeStageValidator.isValidOperatorTransition', () {
    test('deferred → definition is allowed', () {
      expect(
        FeatureChangeStageValidator.isValidOperatorTransition(
          Stage.deferred,
          Stage.definition,
        ),
        isTrue,
      );
    });

    test('deferred → spec_ready is allowed', () {
      expect(
        FeatureChangeStageValidator.isValidOperatorTransition(
          Stage.deferred,
          Stage.specReady,
        ),
        isTrue,
      );
    });

    test('deferred → any other stage (including deferred itself) is rejected',
        () {
      for (final to in Stage.values) {
        if (to == Stage.definition || to == Stage.specReady) continue;
        expect(
          FeatureChangeStageValidator.isValidOperatorTransition(
            Stage.deferred,
            to,
          ),
          isFalse,
          reason:
              'deferred → $to is not an allowed operator un-defer transition',
        );
      }
    });

    test('every non-deferred source rejects every target', () {
      for (final from in Stage.values) {
        if (from == Stage.deferred) continue;
        for (final to in Stage.values) {
          expect(
            FeatureChangeStageValidator.isValidOperatorTransition(from, to),
            isFalse,
            reason:
                'non-deferred sources have no operator-driven transitions: $from → $to must be rejected',
          );
        }
      }
    });
  });

  group('FeatureChangeStageValidator.isOperatorTerminal', () {
    test('merged is operator-terminal', () {
      expect(
        FeatureChangeStageValidator.isOperatorTerminal(Stage.merged),
        isTrue,
      );
    });

    test('deferred is NOT operator-terminal (F7-b: deferred is non-terminal)',
        () {
      expect(
        FeatureChangeStageValidator.isOperatorTerminal(Stage.deferred),
        isFalse,
        reason:
            'F7-b — deferred can be un-deferred so it is not a terminal stage',
      );
    });

    test('no other stage is operator-terminal', () {
      for (final s in Stage.values) {
        if (s == Stage.merged) continue;
        expect(
          FeatureChangeStageValidator.isOperatorTerminal(s),
          isFalse,
          reason: 'only `merged` is operator-terminal; $s must not be',
        );
      }
    });
  });
}
