const clipRecordingCommands = {
  '开始录音': 'AT+START',
  '停止录音': 'AT+STOP',
};
Map<String, dynamic> checkedClipReply(Map<String, dynamic> reply) {
  if (reply['ok'] != true) {
    throw StateError(
        '设备未确认成功：${reply['error'] ?? reply['message'] ?? '请刷新状态后重试'}');
  }
  return reply;
}
