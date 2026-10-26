import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';
import 'package:respeaker_app/src/features/desktop/clip_upload_panel.dart';

class FakeUploadTransport implements AtTransport {
  final events = StreamController<Map<String, dynamic>>.broadcast();
  bool enabled = true;
  @override
  Stream<Map<String, dynamic>> get jsonMessages => events.stream;
  @override
  Future<Map<String, dynamic>> send(String command,
      {Duration timeout = const Duration(seconds: 5),
      bool withoutResponse = false,
      Duration interChunkDelay = const Duration(milliseconds: 16)}) async {
    if (command == 'AT+UPLOADAUTO=off') enabled = false;
    if (command == 'AT+UPLOADAUTO=on') enabled = true;
    return {
      'ok': true,
      'data': switch (command) {
        'AT+UPLOADAUTO?' => {'enabled': enabled, 'time_ready': true},
        'AT+NETCHECK?' => {'state': 'succeeded', 'cleanup_error': 0, 'job': 1},
        _ => {'stage': 'idle', 'confirmed': 0, 'size': 0},
      }
    };
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets(
      'historical terminal events cannot reverse the current automatic switch',
      (tester) async {
    final at = FakeUploadTransport();
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SingleChildScrollView(child: ClipUploadPanel(at: at)))));
    await tester.pumpAndSettle();
    expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value, true);
    at.events.add({
      'event': 'upload',
      'type': 'file_complete',
      'seq': 1,
      'enabled': false,
      'size': 100,
      'confirmed': 100
    });
    await tester.pumpAndSettle();
    expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value, true);
    expect(find.text('设备时间已同步'), findsOneWidget);
    expect(find.textContaining('DHCP'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await at.events.close();
  });
}
