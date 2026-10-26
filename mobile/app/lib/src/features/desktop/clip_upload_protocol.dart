import 'dart:convert';

/// DTLS upload firmware's encrypted BLE command contract.
class ClipUploadProtocol {
  static String _fit(String command, int payload) {
    if (utf8.encode(command).length > payload) {
      throw FormatException('配置超过当前蓝牙单次写入上限（$payload 字节），请缩短配置或重连后重试。');
    }
    return command;
  }

  static String wifi(String ssid, String password, {required int payload}) {
    final name = utf8.encode(ssid).length;
    final secret = utf8.encode(password).length;
    if (name < 1 ||
        name > 32 ||
        secret < 8 ||
        secret > 63 ||
        ssid.contains(',') ||
        '$ssid$password'.contains(RegExp(r'[\x00-\x1f\x7f]'))) {
      throw const FormatException(
          'Wi-Fi 名称须为 1–32 字节且不含逗号，密码须为 8–63 字节，均不能含换行。');
    }
    return _fit('AT+NETCFG=$ssid,$password', payload);
  }

  static String receiver(String endpoint, String device, String token,
      {required int payload}) {
    final match =
        RegExp(r'^([A-Za-z0-9.-]{1,95}):([0-9]{1,5})$').firstMatch(endpoint);
    final port = match == null ? 0 : int.parse(match[2]!);
    if (match == null ||
        port < 1 ||
        port > 65535 ||
        !RegExp(r'^[A-Za-z0-9_-]{1,32}$').hasMatch(device) ||
        !RegExp(r'^[A-Za-z0-9_-]{32,96}$').hasMatch(token)) {
      throw const FormatException(
          '请填写主机:端口、1–32 位设备 ID 和 32–96 位设备令牌；此处不填 https://。');
    }
    return _fit('AT+UPLOADCFG=${match[1]},$port,$device,$token', payload);
  }

  static Map<String, dynamic> data(Map<String, dynamic> reply) =>
      reply['data'] is Map
          ? Map<String, dynamic>.from(reply['data'] as Map)
          : reply;

  static String networkLabel(Map<String, dynamic> value) {
    if ((value['cleanup_error'] as num? ?? 0) != 0) return '检查失败：网络资源清理异常';
    return switch (value['state']) {
      'succeeded' => 'Wi-Fi 与 DHCP 检查通过（尚未验证 Server）',
      'checking' => '正在检查 Wi-Fi 与 DHCP…',
      'failed' => 'Wi-Fi 检查失败（${value['error'] ?? '未知错误'}）',
      'cancelled' => 'Wi-Fi 检查已取消',
      _ => 'Wi-Fi 尚未检查',
    };
  }
}

class ClipUploadSnapshot {
  final Map<String, dynamic> value;
  ClipUploadSnapshot.fromJson(Map<String, dynamic> json)
      : value = ClipUploadProtocol.data(json);
  int get size => (value['size'] as num? ?? 0).toInt();
  int get confirmed => (value['confirmed'] as num? ?? 0).toInt();
  double get progress => size == 0 ? 0 : (confirmed / size).clamp(0, 1);
  bool get complete => value['type'] == 'file_complete';
  String get stage => value['stage']?.toString() ?? 'idle';
  bool get enabled => value['enabled'] == true;
  bool get active => value['active'] == true;
}
