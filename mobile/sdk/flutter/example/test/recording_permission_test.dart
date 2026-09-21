import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice_app/phone_recording.dart';

void main() {
  testWidgets(
      'Denied microphone permission never starts recording or offers save',
      (tester) async {
    final calls = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    const channel = MethodChannel('com.llfbandit.record/messages');
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      if (call.method == 'create') {
        final id = call.arguments['recorderId'];
        messenger.setMockMethodCallHandler(
            MethodChannel('com.llfbandit.record/events/$id'),
            (_) async => null);
      }
      if (call.method == 'hasPermission') return false;
      return null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
    await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: PhoneRecordingSheet())));
    await tester.pumpAndSettle();
    expect(find.text('麦克风权限未开启，请在系统设置中允许录音。'), findsOneWidget);
    expect(calls, isNot(contains('start')));
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '结束并保存'))
            .onPressed,
        isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });
}
