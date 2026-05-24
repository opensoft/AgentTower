import 'package:agenttower_control_panel/core/daemon/mutation_keys.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [MutationKeys] RFC 4122 §4.4 conformance.
/// Review fix H5 / test lane — the masking + `Random.secure()` path was
/// previously untested, so a regression could silently produce
/// predictable keys.
void main() {
  group('MutationKeys.fresh()', () {
    test('produces 36-char UUID v4 strings with hyphens at positions 8/13/18/23',
        () {
      for (var i = 0; i < 100; i++) {
        final key = MutationKeys.fresh();
        expect(key.length, 36, reason: 'iter $i — $key');
        expect(key[8], '-', reason: 'iter $i — $key');
        expect(key[13], '-', reason: 'iter $i — $key');
        expect(key[18], '-', reason: 'iter $i — $key');
        expect(key[23], '-', reason: 'iter $i — $key');
      }
    });

    test('byte 6 high nibble is `4` (version)', () {
      // The version nibble lives at character position 14 (after the
      // 3rd hyphen in the canonical form "xxxxxxxx-xxxx-Vxxx-Yxxx-...").
      for (var i = 0; i < 100; i++) {
        final key = MutationKeys.fresh();
        expect(key[14], '4',
            reason: 'iter $i — UUID v4 version nibble must be `4`: $key');
      }
    });

    test('byte 8 high nibble is `8`, `9`, `a`, or `b` (variant)', () {
      // The variant nibble lives at character position 19.
      for (var i = 0; i < 100; i++) {
        final key = MutationKeys.fresh();
        expect(['8', '9', 'a', 'b'].contains(key[19]), isTrue,
            reason: 'iter $i — UUID v4 variant nibble must be 8/9/a/b: $key');
      }
    });

    test('successive calls produce distinct keys', () {
      final keys = <String>{};
      for (var i = 0; i < 1000; i++) {
        keys.add(MutationKeys.fresh());
      }
      // 1000 v4 UUIDs colliding is astronomically improbable.
      expect(keys.length, 1000);
    });

    test('matches the canonical hex regex', () {
      final pattern = RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$');
      for (var i = 0; i < 100; i++) {
        final key = MutationKeys.fresh();
        expect(pattern.hasMatch(key), isTrue, reason: 'iter $i — $key');
      }
    });
  });
}
