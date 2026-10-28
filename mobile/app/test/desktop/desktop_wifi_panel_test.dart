import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';
import 'package:respeaker_app/src/features/desktop/clip_upload_panel.dart';
import 'package:respeaker_app/src/features/desktop/mac_wifi_scanner.dart';

class TestMtu implements MtuManager {
  @override
  int get payloadSize => 185;
  @override
  dynamic noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

class WifiAt implements AtTransport {
  final events = StreamController<Map<String, dynamic>>.broadcast();
  final commands = <String>[];
  String ssid = 'Clip-Net';
  bool failSave = false;
  @override
  MtuManager get mtu => TestMtu();
  @override
  Stream<Map<String, dynamic>> get jsonMessages => events.stream;
  @override
  Future<Map<String, dynamic>> send(String command,
      {Duration timeout = const Duration(seconds: 5),
      bool withoutResponse = false,
      Duration interChunkDelay = const Duration(milliseconds: 16)}) async {
    commands.add(command);
    if (command.startsWith('AT+NETCFG=')) {
      if (failSave) throw StateError('raw secret must not appear');
      ssid = command.substring(10).split(',').first;
    }
    final wifi = {
      'configured': true,
      'saved': true,
      'ssid_hex': utf8
          .encode(ssid)
          .map((e) => e.toRadixString(16).padLeft(2, '0'))
          .join()
    };
    return {
      'ok': true,
      'data': command.startsWith('AT+NETCFG')
          ? wifi
          : switch (command) {
              'AT+GSTAT' => {'state': 'IDLE', 'recording': false},
              'AT+UPLOADAUTO?' => {'enabled': false},
              'AT+NETCHECK' => {'accepted': true, 'job': 8},
              'AT+NETCHECK?' => {
                  'state': 'succeeded',
                  'cleanup_error': 0,
                  'job': 8,
                  'scope': 'wifi_dhcp'
                },
              _ => {
                  'stage': 'idle',
                  'active': false,
                  'size': 0,
                  'confirmed': 0
                },
            }
    };
  }

  @override
  dynamic noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

MacWifiScanResult fixture() => MacWifiScanResult.fromJson({
      'source': 'macos',
      'current_ssid': 'Mac-5G',
      'networks': [
        {
          'ssid': 'Mac-5G',
          'rssi': -20,
          'band': '5',
          'channel': 36,
          'security': 'wpa2'
        },
        {
          'ssid': 'Office',
          'rssi': -40,
          'band': '2.4',
          'channel': 6,
          'security': 'wpa2'
        }
      ]
    });
Finder field(String label) => find.byWidgetPredicate(
    (w) => w is TextField && w.decoration?.labelText == label);
Widget page(AtTransport? at) => MaterialApp(
    home: Scaffold(
        body: SingleChildScrollView(
            child: ClipUploadPanel(at: at, scanWifi: () async => fixture()))));
void main() {
  testWidgets('scrolling offscreen during scan preserves password and releases parent busy gate', (tester) async {
    tester.view.physicalSize = const Size(1300, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final scan = Completer<MacWifiScanResult>();
    final busy = <bool>[];
    final scroll = ScrollController();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: ListView(controller:scroll, children:[
      ClipUploadPanel(key:const ValueKey('keep-wifi'),at:null,scanWifi:()=>scan.future,onBusyChanged:busy.add),
      const SizedBox(height:5000),
    ]))));
    await tester.pumpAndSettle();
    await tester.enterText(field('Wi-Fi 密码'), 'synthetic-keep-alive');
    await tester.tap(find.text('扫描附近 Wi-Fi'));
    await tester.pump();
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pump();
    scroll.jumpTo(scroll.position.maxScrollExtent);
    await tester.pump(); await tester.pump();
    scan.complete(fixture());
    await tester.pumpAndSettle();
    expect(busy, [true,false], reason:'offscreen completion must release the parent gate');
    scroll.jumpTo(0); await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).controller!.text,'synthetic-keep-alive');
    await tester.pumpWidget(const SizedBox()); scroll.dispose();
  });
  testWidgets(
      'scan, matching and password visibility work without Clip; saving stays disabled',
      (tester) async {
    tester.view.physicalSize = const Size(1300, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(page(null));
    await tester.pumpAndSettle();
    await tester.enterText(field('Wi-Fi 密码'), 'synthetic-test-only');
    await tester.tap(find.text('扫描附近 Wi-Fi'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Mac-5G'), findsWidgets);
    expect(
        tester
            .widget<DropdownButton<String>>(find.byType(DropdownButton<String>))
            .items!
            .firstWhere((e) => e.value == 'Mac-5G')
            .enabled,
        false);
    await tester.enterText(field('Wi-Fi 名称'), 'Manual-Net');
    await tester.tap(find.text('扫描附近 Wi-Fi'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('Wi-Fi 名称')).controller!.text,
        'Manual-Net');
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).controller!.text,
        'synthetic-test-only');
    await tester.tap(find.byTooltip('显示密码'));
    await tester.pump();
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).obscureText, false);
    await tester.tap(find.byTooltip('隐藏密码'));
    await tester.pump();
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).obscureText, true);
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '保存并测试连接'))
            .onPressed,
        isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
      'device SSID overrides Mac on attach; save failure and reconnect preserve password',
      (tester) async {
    tester.view.physicalSize = const Size(1300, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final at = WifiAt();
    await tester.pumpWidget(page(null));
    await tester.pumpAndSettle();
    await tester.enterText(field('Wi-Fi 名称'), 'Mac-Draft');
    await tester.enterText(field('Wi-Fi 密码'), 'synthetic-test-only');
    await tester.pumpWidget(page(at));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('Wi-Fi 名称')).controller!.text,
        'Clip-Net');
    at.failSave = true;
    await tester.tap(find.text('保存并测试连接'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).controller!.text,
        'synthetic-test-only');
    expect(at.commands.contains('AT+NETCHECK'), false);
    await tester.pumpWidget(page(null));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).controller!.text,
        'synthetic-test-only');
    at.failSave = false;
    await tester.pumpWidget(page(at));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存并测试连接'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(at.commands.contains('AT+NETCHECK'), true);
    expect(tester.widget<TextField>(field('Wi-Fi 密码')).controller!.text,
        'synthetic-test-only');
    expect(find.textContaining('DHCP'), findsWidgets);
    await tester.pumpWidget(const SizedBox());
    await at.events.close();
  });
}
