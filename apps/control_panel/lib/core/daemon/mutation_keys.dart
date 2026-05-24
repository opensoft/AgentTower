import 'dart:math';

/// UUID v4 generator for `idempotency_key` on every write surface
/// (T028 + Round-3 R-28). Used by [AppClient] mutation wrappers so
/// retries of the same logical action do not double-submit on the
/// daemon side.
///
/// Uses `Random.secure()` rather than the default `Random()` so the
/// generated keys can't be predicted from prior keys — predictability
/// would let a hostile process on the same host guess a key and
/// pre-submit a mutation that would later be deduplicated against the
/// operator's real action.
class MutationKeys {
  MutationKeys._();

  static final Random _rng = Random.secure();

  /// Returns a fresh UUID v4 string ("xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx").
  static String fresh() {
    final bytes = List<int>.generate(16, (_) => _rng.nextInt(256));
    // Per RFC 4122 §4.4: version (4) goes in the high nibble of byte 6;
    // variant (10xxxxxx) goes in the high nibble of byte 8.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    String hex(int b) => b.toRadixString(16).padLeft(2, '0');
    final hexBytes = bytes.map(hex).toList(growable: false);
    return '${hexBytes.sublist(0, 4).join()}-'
        '${hexBytes.sublist(4, 6).join()}-'
        '${hexBytes.sublist(6, 8).join()}-'
        '${hexBytes.sublist(8, 10).join()}-'
        '${hexBytes.sublist(10, 16).join()}';
  }
}
