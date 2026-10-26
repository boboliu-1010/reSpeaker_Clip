import 'dart:async';
import 'package:flutter/material.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';
import 'clip_protocol.dart';
import 'clip_upload_protocol.dart';

class ClipUploadPanel extends StatefulWidget {
  const ClipUploadPanel({super.key, required this.at, this.serverAddress = ''});
  final AtTransport at;
  final String serverAddress;
  @override
  State<ClipUploadPanel> createState() => _ClipUploadPanelState();
}

class _ClipUploadPanelState extends State<ClipUploadPanel> {
  final _ssid = TextEditingController();
  final _password = TextEditingController();
  final _receiver = TextEditingController();
  final _device = TextEditingController();
  final _token = TextEditingController();
  StreamSubscription<Map<String, dynamic>>? _events;
  ClipUploadSnapshot _upload = ClipUploadSnapshot.fromJson({});
  String _network = 'Wi-Fi 尚未检查';
  String _message = '通过加密蓝牙配置后，Clip 可独立上传。';
  bool _busy = false;
  bool _enabled = false;
  bool _paused = false;
  bool _timeReady = false;
  int? _seq;
  int? _checkJob;
  int _lost = 0;

  @override
  void initState() {
    super.initState();
    final uri = Uri.tryParse(widget.serverAddress);
    if (uri != null && uri.host.isNotEmpty) {
      _receiver.text = '${uri.host}:${uri.port}';
    }
    _listen();
    unawaited(_refresh());
  }

  @override
  void didUpdateWidget(covariant ClipUploadPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.at != widget.at) {
      _events?.cancel();
      _seq = null;
      _checkJob = null;
      _lost = 0;
      _listen();
      unawaited(_refresh());
    }
  }

  void _listen() {
    _events = widget.at.jsonMessages.listen((json) {
      if (!mounted) return;
      final name = json['event'];
      if (name != 'upload' && name != 'wifi_check') return;
      final seq = (json['seq'] as num?)?.toInt();
      final lost = (json['lost'] as num? ?? 0).toInt();
      final gap =
          (_seq != null && seq != null && seq != _seq! + 1) || lost > _lost;
      _seq = seq;
      _lost = lost;
      setState(() {
        if (name == 'upload') {
          _upload = ClipUploadSnapshot.fromJson(json);
          if (json['type'] == 'session_deleted') {
            _message = '录音已上传，设备副本已清理；可刷新服务器音频列表。';
          }
          if (json['type'] == 'session_delete_failed') {
            _message = '录音已上传，设备副本清理失败。';
          }
        } else if (_checkJob == null || json['job'] == _checkJob) {
          _network = ClipUploadProtocol.networkLabel(json);
        }
      });
      if (gap && !_busy) unawaited(_refresh());
    });
  }

  Future<void> _run(Future<void> Function(AtTransport at) action) async {
    if (_busy) return;
    final at = widget.at;
    setState(() => _busy = true);
    try {
      await action(at);
    } on FormatException catch (error) {
      if (mounted) setState(() => _message = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => _message = '设备未确认操作，请检查配对、固件支持和设备空闲状态，再刷新重试。');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<Map<String, dynamic>> _send(AtTransport at, String command) async =>
      ClipUploadProtocol.data(checkedClipReply(await at.send(command)));

  Future<void> _read(AtTransport at) async {
    final upload = await _send(at, 'AT+UPLOAD?');
    final auto = await _send(at, 'AT+UPLOADAUTO?');
    final wifi = await _send(at, 'AT+NETCHECK?');
    if (!mounted || widget.at != at) return;
    setState(() {
      _enabled = auto['enabled'] == true;
      _paused = auto['paused'] == true;
      _timeReady = auto['time_ready'] == true;
      _upload = ClipUploadSnapshot.fromJson(
          {...upload, 'enabled': auto['enabled'], 'paused': auto['paused']});
      _network = ClipUploadProtocol.networkLabel(wifi);
      _checkJob = (wifi['job'] as num?)?.toInt();
    });
  }

  Future<void> _refresh() => _run(_read);

  Future<void> _saveWifi() => _run((at) async {
        final command = ClipUploadProtocol.wifi(_ssid.text, _password.text,
            payload: at.mtu.payloadSize);
        final reply = await _send(at, command);
        if (reply['saved'] != true) throw StateError('not persisted');
        _password.clear();
        if (mounted) {
          setState(() {
            _message = 'Wi-Fi 配置已保存。请检查 Wi-Fi，再开启自动上传。';
            _network = 'Wi-Fi 尚未检查';
            _checkJob = null;
          });
        }
      });

  Future<void> _saveReceiver() => _run((at) async {
        final command = ClipUploadProtocol.receiver(
            _receiver.text.trim(), _device.text.trim(), _token.text.trim(),
            payload: at.mtu.payloadSize);
        // Enrollment changes require the persistent automatic switch to be off.
        await _send(at, 'AT+UPLOADAUTO=off');
        await _send(at, command);
        final saved = await _send(at, 'AT+UPLOADCFG?');
        if (saved['saved'] != true || saved['configured'] != true) {
          throw StateError('not persisted');
        }
        _token.clear();
        if (mounted) {
          setState(() => _message = '上传目标已保存；请确认 Wi-Fi 检查结果，再开启自动上传。');
        }
        await _read(at);
      });

  @override
  void dispose() {
    _events?.cancel();
    for (final value in [_ssid, _password, _receiver, _device, _token]) {
      value.dispose();
    }
    super.dispose();
  }

  Widget _field(TextEditingController controller, String label,
          {bool secret = false}) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: TextField(
              controller: controller,
              obscureText: secret,
              autocorrect: false,
              enableSuggestions: !secret,
              enabled: !_busy,
              decoration: InputDecoration(labelText: label)));

  @override
  Widget build(BuildContext context) => Card(
      child: Padding(
          padding: const EdgeInsets.all(20),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.cloud_upload_outlined, color: Color(0xff167d8d)),
              const SizedBox(width: 10),
              Text('联网与自动上传', style: Theme.of(context).textTheme.titleLarge),
              const Spacer(),
              IconButton(
                  tooltip: '刷新上传状态',
                  onPressed: _busy ? null : _refresh,
                  icon: const Icon(Icons.refresh))
            ]),
            const SizedBox(height: 12),
            Text(_message),
            const SizedBox(height: 12),
            Text(_network),
            Text(_timeReady ? '设备时间已同步' : '设备时间待同步（上传需有效时间）'),
            const SizedBox(height: 12),
            Text(_upload.complete ? '文件上传完成' : '阶段：${_upload.stage}'),
            const SizedBox(height: 8),
            LinearProgressIndicator(value: _upload.progress),
            const SizedBox(height: 8),
            Text(
                '已持久确认 ${_upload.confirmed} / ${_upload.size} 字节 · 错误 ${_upload.value['last_error'] ?? 0}'),
            if (_upload.value['delete_after_upload'] == true)
              const Text('当前固件在整段录音确认上传后自动清理设备副本。'),
            if ((_upload.value['delete_error'] as num? ?? 0) != 0)
              const Text('设备副本清理失败，服务器上传结果不受影响。'),
            SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('自动上传'),
                subtitle:
                    Text(_paused ? '本次调度已暂停，开启可继续' : '设备空闲时上传，断开 App 后仍可继续'),
                value: _enabled,
                onChanged: _busy
                    ? null
                    : (enabled) => _run((at) async {
                          await _send(
                              at, 'AT+UPLOADAUTO=${enabled ? 'on' : 'off'}');
                          await _read(at);
                        })),
            Wrap(spacing: 12, runSpacing: 8, children: [
              OutlinedButton(
                  onPressed: _busy
                      ? null
                      : () => _run((at) async {
                            final reply = await _send(at, 'AT+NETCHECK');
                            _checkJob = (reply['job'] as num?)?.toInt();
                            if (mounted) {
                              setState(() => _network = '正在检查 Wi-Fi 与 DHCP…');
                            }
                          }),
                  child: const Text('检查 Wi-Fi')),
              TextButton(
                  onPressed: _busy
                      ? null
                      : () => _run((at) async {
                            await _send(at, 'AT+UPLOADCANCEL');
                            await _read(at);
                          }),
                  child: const Text('取消上传并暂停调度')),
            ]),
            TextButton.icon(
                onPressed: _busy || _upload.active
                    ? null
                    : () => _run((at) async {
                          await _send(at,
                              'AT+TIME=${DateTime.now().millisecondsSinceEpoch ~/ 1000}');
                          await _read(at);
                        }),
                icon: const Icon(Icons.schedule),
                label: const Text('同步 Mac 时间到 Clip')),
            const Divider(height: 32),
            ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: const Text('Wi-Fi 配置'),
                subtitle: const Text('保存到设备，重启后保留'),
                children: [
                  _field(_ssid, 'Wi-Fi 名称'),
                  _field(_password, 'Wi-Fi 密码', secret: true),
                  Align(
                      alignment: Alignment.centerLeft,
                      child: FilledButton(
                          onPressed: _busy || _upload.active ? null : _saveWifi,
                          child: const Text('保存 Wi-Fi'))),
                ]),
            ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: const Text('Server 与设备凭证'),
                subtitle: const Text('设备令牌由开发者登记，与 App 用户令牌不同'),
                children: [
                  _field(_receiver, 'Server 主机:端口（DTLS）'),
                  _field(_device, '设备 ID'),
                  _field(_token, '设备令牌', secret: true),
                  const Text('保存时会先关闭自动上传；固件需信任 Server 证书且时间有效。'),
                  const SizedBox(height: 12),
                  Align(
                      alignment: Alignment.centerLeft,
                      child: FilledButton(
                          onPressed:
                              _busy || _upload.active ? null : _saveReceiver,
                          child: const Text('保存上传目标'))),
                ]),
            if (_busy)
              const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: LinearProgressIndicator()),
          ])));
}
