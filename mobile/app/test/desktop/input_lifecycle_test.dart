import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/desktop_page.dart';

void main() {
  testWidgets(
      'launching and closing desktop does not initialize microphone plugins',
      (tester) async {
    final root = await tester
        .runAsync(() => Directory.systemTemp.createTemp('boa-input-lifecycle'));
    tester.view.physicalSize = const Size(1100, 760);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var creates = 0;
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'),
        (call) async => root!.path);
    messenger.setMockMethodCallHandler(
        const MethodChannel('com.llfbandit.record/messages'), (call) async {
      if (call.method == 'create') creates++;
      return switch (call.method) {
        'hasPermission' => true,
        'listInputDevices' => [
            {'id': 'test-input', 'label': 'USB 麦克风'}
          ],
        _ => null,
      };
    });
    await tester.pumpWidget(const MaterialApp(home: DesktopPage()));
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pump();
    expect(creates, 0,
        reason:
            'native plugins may not be ready during initial widget creation');
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    expect(creates, 0);
    messenger.setMockMethodCallHandler(
        const MethodChannel('com.llfbandit.record/messages'), null);
    messenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'), null);
    await tester.runAsync(() => root!.delete(recursive: true));
  });
  testWidgets(
      'input refresh is disabled while recording authorization is pending',
      (tester) async {
    final root = await tester
        .runAsync(() => Directory.systemTemp.createTemp('boa-input-busy'));
    tester.view.physicalSize = const Size(1100, 760);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var permission = Completer<bool>();
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'),
        (call) async => root!.path);
    messenger.setMockMethodCallHandler(
        const MethodChannel('com.llfbandit.record/messages'), (call) async {
      if (call.method == 'hasPermission') return permission.future;
      return null;
    });
    await tester.runAsync(() async {
      await tester.pumpWidget(const MaterialApp(home: DesktopPage()));
      await Future<void>.delayed(const Duration(milliseconds: 100));
    });
    await tester.pump();
    final mic = find.widgetWithText(FilledButton, '麦克风录音');
    expect(tester.widget<FilledButton>(mic).onPressed, isNotNull);
    await tester.tap(mic);
    await tester.pump();
    await tester.tap(find.text('服务设置').first);
    await tester.pump();
    final refresh = find.widgetWithText(TextButton, '刷新麦克风列表');
    expect(tester.widget<TextButton>(refresh).onPressed, isNull);
    permission.complete(false);
    await tester.pump();
    permission = Completer<bool>();
    await tester.tap(refresh);
    await tester.pump();
    expect(tester.widget<FilledButton>(mic).onPressed, isNull);
    permission.complete(false);
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await tester.runAsync(() => root!.delete(recursive: true));
  });
}
