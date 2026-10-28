import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';

class MacWifiNetwork {
  MacWifiNetwork(this.ssid, this.rssi, this.band, this.security);
  final String ssid, band, security;
  final int rssi;
  String get reason => ssid.contains(',')
      ? '当前 Clip 不支持名称含逗号'
      : band != '2.4'
          ? '需要 2.4 GHz'
          : security != 'wpa2'
              ? '需要 WPA2 密码网络'
              : '';
  bool get compatible => reason.isEmpty;
  String get label =>
      '$ssid · $rssi dBm · $band GHz · ${compatible ? 'WPA2' : reason}';
}

class MacWifiScanResult {
  MacWifiScanResult(this.currentSsid, this.networks);
  final String currentSsid;
  final List<MacWifiNetwork> networks;
  factory MacWifiScanResult.fromJson(Map<String, dynamic> value) {
    final raw = value['networks'];
    if (value['source'] != 'macos' || raw is! List || raw.length > 128) {
      throw const FormatException('Mac Wi-Fi 扫描响应无效');
    }
    final names = <String, MacWifiNetwork>{};
    for (final entry in raw) {
      if (entry is! Map) continue;
      final ssid = entry['ssid'], rssi = entry['rssi'];
      if (ssid is! String ||
          ssid.isEmpty ||
          utf8.encode(ssid).length > 32 ||
          ssid.contains(RegExp(r'[\x00-\x1f\x7f]')) ||
          rssi is! num ||
          !rssi.isFinite ||
          rssi < -127 ||
          rssi > 0) {
        continue;
      }
      final row = MacWifiNetwork(
          ssid, rssi.toInt(), '${entry['band']}', '${entry['security']}');
      final old = names[ssid];
      if (old == null ||
          (row.compatible && !old.compatible) ||
          (row.compatible == old.compatible && row.rssi > old.rssi)) {
        names[ssid] = row;
      }
    }
    final rows = names.values.toList()
      ..sort((a, b) {
        if (a.compatible != b.compatible) return a.compatible ? -1 : 1;
        final signal = b.rssi.compareTo(a.rssi);
        return signal != 0 ? signal : a.ssid.compareTo(b.ssid);
      });
    return MacWifiScanResult(
        value['current_ssid'] is String ? value['current_ssid'] as String : '',
        rows);
  }
  String get defaultSsid => selectionFor(currentSsid) ?? '';
  String targetFor(String current) =>
      current.isNotEmpty ? current : defaultSsid;
  String? selectionFor(String target) =>
      networks.any((n) => n.compatible && n.ssid == target) ? target : null;
}

class MacWifiScanner {
  static const _channel = MethodChannel('boa_voice/wifi');
  static Future<MacWifiScanResult> scan() async {
    try {
      final raw = await _channel
          .invokeMapMethod<String, dynamic>('scan')
          .timeout(const Duration(seconds: 40));
      return MacWifiScanResult.fromJson(Map<String, dynamic>.from(raw ?? {}));
    } on PlatformException catch (e) {
      throw FormatException(switch (e.code) {
        'location_disabled' => '请开启 Mac 定位服务，并允许 Boa Voice 读取 Wi-Fi 名称。',
        'permission_denied' ||
        'permission_pending' ||
        'ssid_unavailable' =>
          '请在系统设置 → 隐私与安全性 → 定位服务中允许 Boa Voice，再扫描。',
        'wifi_off' => '请先打开 Mac 的 Wi-Fi。',
        'busy' => 'Mac 正在扫描，请稍后重试。',
        _ => 'Mac Wi-Fi 扫描失败，请检查权限后重试。',
      });
    } on TimeoutException {
      throw const FormatException('Mac Wi-Fi 扫描超时，请检查定位授权后重试。');
    } on MissingPluginException {
      throw const FormatException('此版本尚未提供 Mac Wi-Fi 扫描，请使用新版桌面端。');
    }
  }
}
