import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../domain/models/attention_item.dart';

/// FR-053 + SC-008a — interaction-stability window. T136 (Phase 8 US6).
///
/// Per spec clarify Q-Interaction (round 1): the window is **2 seconds
/// since the operator's last hover, click, or keypress on the attention
/// queue**. Live updates received during the window are queued and
/// applied at the next stable point after the window elapses.
///
/// **Stability invariant**: no item under the operator's pointer
/// changes position within the window. The controller keeps a
/// `_pendingList` while the window is active and swaps to it once
/// the timer elapses. SC-008a's "no position change under pointer
/// for ≥ 2 s across 100 simulated bursts" is measured against this
/// invariant.
///
/// Usage from the queue widget:
///   - On hover/click/keypress → call [noteInteraction()].
///   - Subscribe to [stableList] (a [ValueListenable]) to render.
///   - Push provider updates via [acceptIncoming(items)].
///
/// The controller is intentionally [ChangeNotifier]-based rather than
/// Riverpod-based so widget tests can drive it deterministically
/// without provider plumbing.
class InteractionStabilityController extends ChangeNotifier
    implements ValueListenable<List<AttentionItem>> {
  InteractionStabilityController({
    Duration windowDuration = const Duration(seconds: 2),
    DateTime Function() now = _defaultNow,
  })  : _windowDuration = windowDuration,
        _now = now;

  final Duration _windowDuration;
  final DateTime Function() _now;

  List<AttentionItem> _stableList = const <AttentionItem>[];
  List<AttentionItem>? _pendingList;
  DateTime? _lastInteractionAt;
  Timer? _swapTimer;

  /// The list the queue widget should render. Updates are deferred
  /// while [isInWindow] is true; when the window elapses, [stableList]
  /// transitions to the most-recent `_pendingList` value.
  List<AttentionItem> get stableList => _stableList;

  @override
  List<AttentionItem> get value => _stableList;

  /// True iff we are inside the post-interaction stability window.
  bool get isInWindow {
    final last = _lastInteractionAt;
    if (last == null) return false;
    return _now().difference(last) < _windowDuration;
  }

  /// Operator interacted with the queue (hover / click / keypress).
  /// Re-arms the stability timer; pending updates wait.
  void noteInteraction() {
    _lastInteractionAt = _now();
    _scheduleSwapIfPending();
  }

  /// New data arrived from the provider. If the operator is mid-
  /// interaction, hold it as pending; otherwise apply immediately.
  void acceptIncoming(List<AttentionItem> items) {
    if (isInWindow) {
      _pendingList = items;
      _scheduleSwapIfPending();
      return;
    }
    _stableList = items;
    _pendingList = null;
    notifyListeners();
  }

  void _scheduleSwapIfPending() {
    _swapTimer?.cancel();
    if (_pendingList == null) return;
    final last = _lastInteractionAt ?? _now();
    final remaining = _windowDuration - _now().difference(last);
    final delay = remaining.isNegative ? Duration.zero : remaining;
    _swapTimer = Timer(delay, _swap);
  }

  void _swap() {
    if (isInWindow) {
      // Operator interacted again during the wait — re-arm.
      _scheduleSwapIfPending();
      return;
    }
    final pending = _pendingList;
    if (pending == null) return;
    _stableList = pending;
    _pendingList = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _swapTimer?.cancel();
    super.dispose();
  }

  static DateTime _defaultNow() => DateTime.now();
}
