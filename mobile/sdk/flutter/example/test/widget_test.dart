import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice_app/main.dart';

void main() {
  testWidgets('Library searches sample recordings and opens their detail',
      (tester) async {
    tester.view.resetPhysicalSize();
    tester.view.physicalSize = const Size(402, 874);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const SenseCraftVoiceDemoApp());
    await tester.pumpAndSettle();
    expect(find.text('本地录音'), findsWidgets);
    await tester.enterText(find.byType(TextField).first, '产品');
    await tester.pumpAndSettle();
    expect(find.text('产品设计周会'), findsOneWidget);
    expect(find.text('散步时的灵感'), findsNothing);
    await tester.tap(find.text('产品设计周会'));
    await tester.pumpAndSettle();
    expect(find.text('示例转写 · 非真实识别结果'), findsOneWidget);
    await tester.tap(find.text('摘要'));
    await tester.pumpAndSettle();
    expect(find.text('核心结论'), findsOneWidget);
  });

  testWidgets('Settings opens separate speech and text API configuration',
      (tester) async {
    tester.view.physicalSize = const Size(402, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const SenseCraftVoiceDemoApp());
    await tester.pumpAndSettle();
    await tester.tap(find.text('我的').last);
    await tester.pumpAndSettle();
    expect(find.text('模型 API'), findsOneWidget);
    expect(find.text('语音识别与文本模型 · 本机安全存储'), findsOneWidget);
  });
}
