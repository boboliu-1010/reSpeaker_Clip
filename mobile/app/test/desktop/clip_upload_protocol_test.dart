import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/clip_upload_protocol.dart';

void main() {
  test('provisioning validates UTF8 limits and a single GATT write', () {
    expect(ClipUploadProtocol.wifi('测试网络', 'password,ok', payload: 185),
        'AT+NETCFG=测试网络,password,ok');
    expect(() => ClipUploadProtocol.wifi('a,b', 'password1', payload: 185),
        throwsFormatException);
    expect(() => ClipUploadProtocol.wifi('wifi', 'short', payload: 185),
        throwsFormatException);
    expect(() => ClipUploadProtocol.wifi('wifi', 'password1', payload: 20),
        throwsFormatException);
    expect(
        () => ClipUploadProtocol.receiver(
            'https://host:9528', 'clip01', 'x' * 40,
            payload: 185),
        throwsFormatException);
    expect(
        ClipUploadProtocol.receiver('host.test:9528', 'clip01', 'x' * 40,
            payload: 185),
        'AT+UPLOADCFG=host.test,9528,clip01,${'x' * 40}');
  });
  test('only completed upload, not receive credit, is presented as complete',
      () {
    final sending = ClipUploadSnapshot.fromJson({
      'event': 'upload',
      'stage': 'sending',
      'sent': 100,
      'received': 100,
      'confirmed': 50,
      'size': 100,
      'active': true
    });
    expect(sending.progress, .5);
    expect(sending.complete, false);
    expect(
        ClipUploadSnapshot.fromJson({
          'event': 'upload',
          'type': 'file_complete',
          'confirmed': 100,
          'size': 100
        }).complete,
        true);
    expect(
        ClipUploadSnapshot.fromJson({
          'ok': true,
          'data': {'kind': 'upload', 'confirmed': 10, 'size': 20}
        }).progress,
        .5);
  });
  test('network validation never promises receiver connectivity', () {
    expect(
        ClipUploadProtocol.networkLabel(
            {'state': 'succeeded', 'cleanup_error': 0}),
        contains('DHCP'));
    expect(
        ClipUploadProtocol.networkLabel(
            {'state': 'succeeded', 'cleanup_error': -5}),
        contains('失败'));
  });
}
