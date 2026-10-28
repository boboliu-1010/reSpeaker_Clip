/// Values are present only when acknowledged by firmware; units follow GSTAT.
class ClipStatus {
  final String? firmware;
  final String state;
  final int? battery, durationSeconds, freeMB;
  final bool? charging;
  const ClipStatus(
      {this.firmware,
      this.state = '未知',
      this.battery,
      this.durationSeconds,
      this.freeMB,
      this.charging});

  factory ClipStatus.fromReplies(Map version, Map status) {
    final data = status['ok'] == true && status['data'] is Map
        ? status['data'] as Map
        : const {};
    int? number(String key) {
      final value = data[key];
      return value is num && value.isFinite && value >= 0
          ? value.toInt()
          : null;
    }

    final rawState = data['state']?.toString().toUpperCase();
    final state = switch (rawState) {
      'RECORDING' => '录音中',
      'PAUSED' => '已暂停',
      'IDLE' => '空闲',
      'TRANSMITTING' => '传输中',
      'WIFI_SYNC' => 'Wi-Fi 同步中',
      'OTA' => '固件升级中',
      'ERROR' => '设备异常',
      'UNINITIALIZED' => '初始化中',
      _ => data['recording'] == true ? '录音中' : '未知',
    };
    final battery = number('battery');
    return ClipStatus(
      firmware: version['ok'] == true && version['firmware'] is String
          ? version['firmware'] as String
          : null,
      state: state,
      battery: battery != null && battery <= 100 ? battery : null,
      durationSeconds: number('duration'),
      freeMB: number('free_space'),
      charging: data['charging'] is bool ? data['charging'] as bool : null,
    );
  }
}
