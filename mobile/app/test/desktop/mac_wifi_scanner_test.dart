import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/mac_wifi_scanner.dart';

Map<String, dynamic> row(String ssid, int rssi,
        {String band = '2.4', String security = 'wpa2'}) =>
    {
      'ssid': ssid,
      'rssi': rssi,
      'band': band,
      'security': security,
      'channel': 1
    };
void main() {
  test(
      'matching prefers compatible band for the same SSID then signal strength',
      () {
    final result = MacWifiScanResult.fromJson({
      'source': 'macos',
      'current_ssid': 'Dual',
      'networks': [
        row('Dual', -15, band: '5'),
        row('Dual', -65),
        row('Near', -30),
        row('Open', -10, security: 'open'),
        row('bad,name', -20)
      ]
    });
    expect(result.networks.map((e) => e.ssid).toList(),
        ['Near', 'Dual', 'Open', 'bad,name']);
    expect(result.networks[1].band, '2.4');
    expect(result.defaultSsid, 'Dual');
    expect(result.targetFor('Clip-Net'), 'Clip-Net');
    expect(result.selectionFor('Clip-Net'), isNull);
  });
  test(
      '5GHz current network is not automatically selected; hidden and invalid names excluded',
      () {
    final result = MacWifiScanResult.fromJson({
      'source': 'macos',
      'current_ssid': 'Mac-5G',
      'networks': [
        row('Mac-5G', -20, band: '5'),
        row('', -30),
        row('网' * 11, -40),
        row('bad\n', -50),
        row('Office', -60)
      ]
    });
    expect(result.defaultSsid, '');
    expect(result.networks.length, 2);
    expect(result.networks.first.ssid, 'Office');
    expect(result.networks.last.compatible, false);
    expect(result.targetFor('Manual'), 'Manual');
    expect(result.selectionFor('Office'), 'Office');
  });
  test('malformed native responses fail rather than claim no networks', () {
    expect(
        () => MacWifiScanResult.fromJson({'source': 'other', 'networks': []}),
        throwsFormatException);
    expect(
        () => MacWifiScanResult.fromJson(
            {'source': 'macos', 'networks': List.filled(129, row('a', -50))}),
        throwsFormatException);
  });
}
