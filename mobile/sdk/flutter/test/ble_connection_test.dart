import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_blue_plus/flutter_blue_plus.dart' as fbp;
import 'package:flutter_blue_plus_platform_interface/flutter_blue_plus_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';

// Replace only native radio operations; exercise the real FlutterBluePlus GATT
// layer, descriptor handling, SDK connection setup and AT transport.
final class _Radio extends FlutterBluePlusPlatform {
  final adapterStates =
      StreamController<BmBluetoothAdapterState>.broadcast(sync: true);
  var adapter = BmAdapterStateEnum.on;
  final statesAtConnect = <BmAdapterStateEnum>[];

  void emitAdapter(BmAdapterStateEnum state) {
    adapter = state;
    adapterStates.add(BmBluetoothAdapterState(adapterState: state));
  }

  @override
  Stream<BmBluetoothAdapterState> get onAdapterStateChanged =>
      adapterStates.stream;
  final links =
      StreamController<BmConnectionStateResponse>.broadcast(sync: true);
  final services =
      StreamController<BmDiscoverServicesResult>.broadcast(sync: true);
  final descriptors = StreamController<BmDescriptorData>.broadcast(sync: true);
  final descriptorReads =
      StreamController<BmDescriptorData>.broadcast(sync: true);
  final writes = StreamController<BmCharacteristicData>.broadcast(sync: true);
  final values = StreamController<BmCharacteristicData>.broadcast(sync: true);
  final rssi = StreamController<BmReadRssiResult>.broadcast(sync: true);
  final connected = <DeviceIdentifier>{};
  var generations = 0;
  bool failDiscovery = false, failFileNotify = false;
  int authFailures = 0, responseAttempts = 0;
  bool answerGstat = true;

  @override
  Stream<BmConnectionStateResponse> get onConnectionStateChanged =>
      links.stream;
  @override
  Stream<BmDiscoverServicesResult> get onDiscoveredServices => services.stream;
  @override
  Stream<BmDescriptorData> get onDescriptorWritten => descriptors.stream;
  @override
  Stream<BmDescriptorData> get onDescriptorRead => descriptorReads.stream;
  @override
  Stream<BmCharacteristicData> get onCharacteristicWritten => writes.stream;
  @override
  Stream<BmCharacteristicData> get onCharacteristicReceived => values.stream;
  @override
  Stream<BmReadRssiResult> get onReadRssi => rssi.stream;
  @override
  Future<BmBluetoothAdapterState> getAdapterState(
          BmBluetoothAdapterStateRequest request) async =>
      BmBluetoothAdapterState(adapterState: adapter);

  void link(DeviceIdentifier id, BmConnectionStateEnum state) {
    links.add(BmConnectionStateResponse(
      remoteId: id,
      connectionState: state,
      disconnectReasonCode: null,
      disconnectReasonString: null,
    ));
  }

  @override
  Future<bool> connect(BmConnectRequest request) async {
    statesAtConnect.add(adapter);
    if (adapter != BmAdapterStateEnum.on) {
      throw StateError('CoreBluetooth is not ready');
    }
    if (!connected.add(request.remoteId)) return false;
    generations++;
    scheduleMicrotask(
        () => link(request.remoteId, BmConnectionStateEnum.connected));
    return true;
  }

  @override
  Future<bool> disconnect(BmDisconnectRequest request) async {
    if (!connected.remove(request.remoteId)) return false;
    scheduleMicrotask(
        () => link(request.remoteId, BmConnectionStateEnum.disconnected));
    return true;
  }

  @override
  Future<bool> discoverServices(BmDiscoverServicesRequest request) async {
    if (failDiscovery) throw StateError('native discovery failed');
    final service = SenseCraftVoiceBleUuids.clipAtService;
    final chars = [
      SenseCraftVoiceBleUuids.commandRxCharacteristic,
      SenseCraftVoiceBleUuids.responseTxCharacteristic,
      SenseCraftVoiceBleUuids.fileDataCharacteristic,
    ]
        .map((uuid) => BmBluetoothCharacteristic(
              remoteId: request.remoteId,
              primaryServiceUuid: null,
              serviceUuid: service,
              characteristicUuid: uuid,
              instanceId: 0,
              descriptors:
                  uuid == SenseCraftVoiceBleUuids.commandRxCharacteristic
                      ? []
                      : [
                          BmBluetoothDescriptor(
                              remoteId: request.remoteId,
                              primaryServiceUuid: null,
                              serviceUuid: service,
                              characteristicUuid: uuid,
                              descriptorUuid: Guid('2902'),
                              instanceId: 0)
                        ],
              properties: BmCharacteristicProperties(
                broadcast: false,
                read: false,
                writeWithoutResponse:
                    uuid == SenseCraftVoiceBleUuids.commandRxCharacteristic,
                write: false,
                notify: uuid != SenseCraftVoiceBleUuids.commandRxCharacteristic,
                indicate: false,
                authenticatedSignedWrites: false,
                extendedProperties: false,
                notifyEncryptionRequired: false,
                indicateEncryptionRequired: false,
              ),
            ))
        .toList();
    scheduleMicrotask(() => services.add(BmDiscoverServicesResult(
          remoteId: request.remoteId,
          services: [
            BmBluetoothService(
                remoteId: request.remoteId,
                primaryServiceUuid: null,
                serviceUuid: service,
                characteristics: chars)
          ],
          success: true,
          errorCode: 0,
          errorString: '',
        )));
    return true;
  }

  @override
  Future<bool> setNotifyValue(BmSetNotifyValueRequest request) async {
    var code = 0;
    if (request.enable &&
        request.characteristicUuid ==
            SenseCraftVoiceBleUuids.responseTxCharacteristic) {
      responseAttempts++;
      if (authFailures > 0) {
        authFailures--;
        code = 15;
      }
    }
    if (request.enable &&
        failFileNotify &&
        request.characteristicUuid ==
            SenseCraftVoiceBleUuids.fileDataCharacteristic) {
      code = 6;
    }
    scheduleMicrotask(() => descriptors.add(BmDescriptorData(
          remoteId: request.remoteId,
          primaryServiceUuid: null,
          serviceUuid: request.serviceUuid,
          characteristicUuid: request.characteristicUuid,
          instanceId: request.instanceId,
          descriptorUuid: Guid('2902'),
          value: [request.enable && code == 0 ? 1 : 0, 0],
          success: code == 0,
          errorCode: code,
          errorString:
              code == 15 ? 'Insufficient encryption' : 'Request not supported',
        )));
    return true;
  }

  @override
  Future<bool> writeCharacteristic(BmWriteCharacteristicRequest request) async {
    BmCharacteristicData packet(Guid uuid, List<int> bytes) =>
        BmCharacteristicData(
          remoteId: request.remoteId,
          primaryServiceUuid: null,
          serviceUuid: request.serviceUuid,
          characteristicUuid: uuid,
          instanceId: request.instanceId,
          value: bytes,
          success: true,
          errorCode: 0,
          errorString: '',
        );
    scheduleMicrotask(
        () => writes.add(packet(request.characteristicUuid, request.value)));
    if (answerGstat && utf8.decode(request.value) == 'AT+GSTAT') {
      Future<void>.delayed(const Duration(milliseconds: 1), () {
        values.add(packet(SenseCraftVoiceBleUuids.responseTxCharacteristic,
            utf8.encode('{"ok":true,"data":{"state":"idle","battery":88}}')));
      });
    }
    return true;
  }

  @override
  Future<bool> readRssi(BmReadRssiRequest request) async {
    scheduleMicrotask(() => rssi.add(BmReadRssiResult(
        remoteId: request.remoteId,
        rssi: -45,
        success: true,
        errorCode: 0,
        errorString: '')));
    return true;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final radio = _Radio();
  final sdk = SenseCraftVoiceClient();
  var sequence = 0;
  late BluetoothDevice device;
  late ScanResult result;
  setUpAll(() => FlutterBluePlusPlatform.instance = radio);
  setUp(() {
    radio.emitAdapter(BmAdapterStateEnum.on);
    radio.statesAtConnect.clear();
    radio.failDiscovery = radio.failFileNotify = false;
    radio.authFailures = radio.responseAttempts = 0;
    radio.answerGstat = true;
    device = BluetoothDevice.fromId('mac-clip-${sequence++}');
    result = ScanResult(
        device: device,
        advertisementData: fbp.AdvertisementData(
            advName: 'Clip',
            txPowerLevel: null,
            appearance: null,
            connectable: true,
            manufacturerData: {},
            serviceData: {},
            serviceUuids: []),
        rssi: -45,
        timeStamp: DateTime.now());
  });
  tearDown(() async => device.disconnect(queue: false));

  test('Apple remembered-device connect waits for cold adapter initialization',
      () async {
    radio.emitAdapter(BmAdapterStateEnum.unknown);
    final pending = sdk.connectByDeviceIdAndVerify(device.remoteId.str);
    await Future<void>.delayed(const Duration(milliseconds: 50));
    final premature = List.of(radio.statesAtConnect);
    radio.emitAdapter(BmAdapterStateEnum.on);
    final connection = await pending;
    expect(premature, isEmpty);
    expect(radio.statesAtConnect, [BmAdapterStateEnum.on]);
    expect(connection, isNotNull);
    await sdk.disconnect(connection!);
  }, skip: !Platform.isMacOS && !Platform.isIOS);

  for (final state in [
    BmAdapterStateEnum.off,
    BmAdapterStateEnum.unauthorized,
    BmAdapterStateEnum.unavailable,
  ]) {
    test('Apple ${state.name} adapter rejects connect before native request',
        () async {
      radio.emitAdapter(state);
      await expectLater(sdk.connect(result), throwsStateError);
      expect(radio.statesAtConnect, isEmpty);
    }, skip: !Platform.isMacOS && !Platform.isIOS);
  }

  test('discovery failure closes native link before returning the error',
      () async {
    radio.failDiscovery = true;
    await expectLater(sdk.connect(result), throwsA(anything));
    expect(device.isDisconnected, isTrue);
  });

  test('file notification failure rolls back the partially initialized link',
      () async {
    radio.failFileNotify = true;
    await expectLater(sdk.connect(result), throwsA(anything));
    expect(device.isDisconnected, isTrue);
  });

  test('retry after failed setup creates a fresh native connection', () async {
    final before = radio.generations;
    radio.failDiscovery = true;
    await expectLater(sdk.connect(result), throwsA(anything));
    radio.failDiscovery = false;
    final conn = await sdk.connect(result);
    expect(radio.generations - before, 2);
    await sdk.disconnect(conn);
  });

  test(
      'Apple encrypted notification setup tolerates pairing beyond three short retries',
      () async {
    radio.authFailures = 3;
    final conn = await sdk.connect(result);
    expect(conn.responseTx.isNotifying, isTrue,
        reason:
            'Response CCCD: ${conn.responseTx.descriptors.map((d) => '${d.uuid}:${d.lastValue}').join(',')}');
    expect(conn.fileData.isNotifying, isTrue);
    await sdk.disconnect(conn);
  }, skip: !Platform.isMacOS && !Platform.isIOS);

  test('Apple permanent encryption failure stops retrying and closes the link',
      () async {
    radio.authFailures = 100;
    await expectLater(sdk.connect(result), throwsA(anything));
    expect(radio.responseAttempts, 8);
    expect(device.isDisconnected, isTrue);
  }, skip: !Platform.isMacOS && !Platform.isIOS);

  test('one connection reuses its AT transport and command queue', () async {
    final conn = await sdk.connect(result);
    expect(
        identical(conn.createAtTransport(), conn.createAtTransport()), isTrue);
    await sdk.disconnect(conn);
  });

  test('verified connection requires an actual AT response', () async {
    final conn = await sdk.connectAndVerify(result);
    expect(conn, isNotNull);
    expect(conn!.device.isConnected, isTrue);
    await sdk.disconnect(conn);
  });

  test('silent AT channel is disconnected instead of returned as ready',
      () async {
    radio.answerGstat = false;
    final conn = await sdk.connectAndVerify(result,
        attempts: 1, verifyTimeout: const Duration(milliseconds: 20));
    expect(conn, isNull);
    expect(device.isDisconnected, isTrue);
  });
}
