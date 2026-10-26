import 'dart:async';
import 'dart:io';

import 'package:flutter_blue_plus_platform_interface/flutter_blue_plus_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';

final class _BluetoothPlatform extends FlutterBluePlusPlatform {
  final states =
      StreamController<BmBluetoothAdapterState>.broadcast(sync: true);
  var state = BmAdapterStateEnum.unknown;
  final statesAtScan = <BmAdapterStateEnum>[];

  void emit(BmAdapterStateEnum value) {
    state = value;
    states.add(BmBluetoothAdapterState(adapterState: value));
  }

  @override
  Stream<BmBluetoothAdapterState> get onAdapterStateChanged => states.stream;

  @override
  Future<BmBluetoothAdapterState> getAdapterState(
          BmBluetoothAdapterStateRequest request) async =>
      BmBluetoothAdapterState(adapterState: state);

  @override
  Future<bool> startScan(BmScanSettings request) async {
    statesAtScan.add(state);
    return true;
  }

  @override
  Future<bool> stopScan(BmStopScanRequest request) async => true;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final platform = _BluetoothPlatform();
  final client = SenseCraftVoiceClient();

  setUpAll(() => FlutterBluePlusPlatform.instance = platform);
  setUp(() => platform.statesAtScan.clear());
  tearDown(() async => client.stopScan());

  test('Apple scan waits for cold adapter initialization before native scan',
      () async {
    platform.emit(BmAdapterStateEnum.unknown);
    final scan = client.startScan();
    await Future<void>.delayed(const Duration(milliseconds: 400));
    platform.emit(BmAdapterStateEnum.on);
    await scan;
    expect(platform.statesAtScan, [BmAdapterStateEnum.on]);
  }, skip: !Platform.isMacOS && !Platform.isIOS);

  for (final state in [
    BmAdapterStateEnum.off,
    BmAdapterStateEnum.unauthorized,
    BmAdapterStateEnum.unavailable,
  ]) {
    test('Apple ${state.name} adapter fails without starting native scan',
        () async {
      platform.emit(state);
      await expectLater(client.startScan(), throwsStateError);
      expect(platform.statesAtScan, isEmpty);
    }, skip: !Platform.isMacOS && !Platform.isIOS);
  }
}
