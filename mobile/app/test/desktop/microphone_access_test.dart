import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/microphone_access.dart';

void main() {
  test('input refresh checks permission without opening a system prompt',
      () async {
    bool? requested;
    await expectLater(requireMicrophonePermission((request) async {
      requested = request;
      return false;
    }), throwsFormatException);
    expect(requested, false);
  });
  test(
      'unanswered system permission frees UI and late grant does not continue recording',
      () async {
    final permission = Completer<bool>();
    var resets = 0, starts = 0;
    Future<void> start() async {
      await requireMicrophonePermission((_) => permission.future,
          request: true,
          timeout: const Duration(milliseconds: 5),
          stalled: () => resets++);
      starts++;
    }

    await expectLater(start(), throwsFormatException);
    permission.complete(true);
    await Future<void>.delayed(Duration.zero);
    expect(resets, 1);
    expect(starts, 0);
  });
}
