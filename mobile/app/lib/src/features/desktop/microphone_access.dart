import 'dart:async';

/// Refresh is a non-prompting check; explicit recording may request access.
/// A late system reply must not resume a recording the user thinks failed.
Future<void> requireMicrophonePermission(Future<bool> Function(bool) check,
    {bool request = false,
    Duration timeout = const Duration(seconds: 20),
    void Function()? stalled}) async {
  bool granted;
  try {
    granted = await check(request).timeout(timeout);
  } on TimeoutException {
    stalled?.call();
    throw const FormatException(
        '系统尚未完成麦克风授权。请亲自处理系统弹窗，或在系统设置 → 隐私与安全性 → 麦克风重新确认 Boa Voice 权限，再重试录音。');
  }
  if (!granted) {
    throw FormatException(request
        ? '麦克风未授权，请在系统设置 → 隐私与安全性 → 麦克风中允许 Boa Voice'
        : '麦克风尚未授权。点击“麦克风录音”请求权限；如系统已列出 Boa Voice，请重新确认本版本的权限。');
  }
}
