import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';
import 'src/features/desktop/desktop_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  unawaited(FlutterBluePlus.setLogLevel(LogLevel.warning));
  SdkLog.bind((level, message, error, stack) {
    // Connection diagnostics only; do not print raw AT payloads or file data.
    if (message.startsWith('BLE ') ||
        message.startsWith('Connecting to ') ||
        message.startsWith('SenseCraftVoiceClient')) {
      debugPrint('[Clip] $message${error == null ? '' : ' | $error'}');
    }
  });
  runApp(MaterialApp(
    title: 'Boa Voice',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff167d8d)),
      scaffoldBackgroundColor: const Color(0xfff6f7f9),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        isDense: true,
      ),
    ),
    home: const DesktopPage(),
  ));
}
