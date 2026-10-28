import 'dart:async';
import 'package:flutter/material.dart';
import 'package:sensecraft_voice/sensecraft_voice.dart';
import 'clip_protocol.dart';
import 'clip_upload_protocol.dart';
import 'mac_wifi_scanner.dart';

class ClipUploadPanel extends StatefulWidget {
  const ClipUploadPanel(
      {super.key,
      required this.at,
      this.serverAddress = '',
      this.deviceBusy = false,
      this.onBusyChanged,
      this.scanWifi});
  final AtTransport? at;
  final String serverAddress;
  final bool deviceBusy;
  final ValueChanged<bool>? onBusyChanged;
  final Future<MacWifiScanResult> Function()? scanWifi;
  @override
  State<ClipUploadPanel> createState() => _ClipUploadPanelState();
}

class _ClipUploadPanelState extends State<ClipUploadPanel>
    with AutomaticKeepAliveClientMixin<ClipUploadPanel> {
  @override
  bool get wantKeepAlive => true;
  final _ssid = TextEditingController(), _password = TextEditingController();
  final _receiver = TextEditingController(),
      _device = TextEditingController(),
      _token = TextEditingController();
  StreamSubscription<Map<String, dynamic>>? _events;
  ClipUploadSnapshot _upload = ClipUploadSnapshot.fromJson({});
  MacWifiScanResult? _scan;
  String _scanMessage = '由这台 Mac 扫描，选择 2.4 GHz / WPA2 网络；也可以手动填写。';
  String _savedSsid = '', _network = 'Wi-Fi 尚未检查';
  String _message = '连接 Clip 后可保存配置并测试；Mac 扫描不改变电脑网络。';
  bool _busy = false,
      _scanningWifi = false,
      _showPassword = false,
      _nameEdited = false;
  bool _enabled = false,
      _paused = false,
      _timeReady = false,
      _needsRead = false,
      _readScheduled = false;
  int _revision = 0, _eventOrder = 0;
  int? _seq, _checkJob;
  int _lost = 0;
  bool get _blocked => _busy || widget.deviceBusy;

  @override
  void initState() {
    super.initState();
    final uri = Uri.tryParse(widget.serverAddress);
    if (uri != null && uri.host.isNotEmpty) {
      _receiver.text = '${uri.host}:${uri.port}';
    }
    _needsRead = widget.at != null;
    _listen();
    _scheduleRead();
  }

  @override
  void didUpdateWidget(covariant ClipUploadPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.at != widget.at) {
      _revision++;
      _events?.cancel();
      _seq = null;
      _checkJob = null;
      _lost = 0;
      _savedSsid = '';
      _network = 'Wi-Fi 尚未检查';
      _nameEdited = false;
      _upload = ClipUploadSnapshot.fromJson({});
      _needsRead = widget.at != null;
      _listen();
    }
    _scheduleRead();
  }

  void _scheduleRead() {
    if (!_needsRead || _readScheduled || _blocked || widget.at == null) return;
    _readScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _readScheduled = false;
      if (mounted && _needsRead && !_blocked && widget.at != null) {
        _needsRead = false;
        unawaited(_run((at) => _read(at, forceName: true)));
      }
    });
  }

  void _listen() {
    final at = widget.at;
    if (at == null) return;
    _events = at.jsonMessages.listen((json) {
      if (!mounted || widget.at != at) return;
      final name = json['event'];
      if (name != 'upload' && name != 'wifi_check') return;
      final seq = (json['seq'] as num?)?.toInt(),
          lost = (json['lost'] as num? ?? 0).toInt();
      final gap =
          (_seq != null && seq != null && seq != _seq! + 1) || lost > _lost;
      _seq = seq;
      _lost = lost;
      _eventOrder++;
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
      if (gap && !_blocked) unawaited(_run(_read));
    });
  }

  void _setBusy(bool value) {
    if (!mounted) return;
    setState(() => _busy = value);
    widget.onBusyChanged?.call(value);
  }

  Future<void> _run(Future<void> Function(AtTransport) task) async {
    if (_blocked || widget.at == null) return;
    final at = widget.at!, revision = _revision;
    _setBusy(true);
    try {
      await task(at);
    } on FormatException catch (e) {
      if (mounted && revision == _revision) {
        setState(() => _message = e.message);
      }
    } catch (_) {
      if (mounted && revision == _revision) {
        setState(() => _message = '设备未确认操作，请检查配对、固件支持与空闲状态后重试。');
      }
    } finally {
      _setBusy(false);
      _scheduleRead();
    }
  }

  Future<Map<String, dynamic>> _send(AtTransport at, String command) async {
    if (!mounted || widget.at != at) {
      throw const FormatException('Clip 连接已变化，请重新读取设备状态。');
    }
    final reply = await at.send(command);
    if (!mounted || widget.at != at) {
      throw const FormatException('Clip 连接已变化，请重新读取设备状态。');
    }
    return ClipUploadProtocol.data(checkedClipReply(reply));
  }

  Future<void> _read(AtTransport at, {bool forceName = false}) async {
    final order = _eventOrder;
    final upload = await _send(at, 'AT+UPLOAD?');
    final automatic = await _send(at, 'AT+UPLOADAUTO?');
    final wifi = await _send(at, 'AT+NETCFG?');
    final network = await _send(at, 'AT+NETCHECK?');
    if (!mounted || widget.at != at) return;
    final name = ClipUploadProtocol.ssid(wifi);
    setState(() {
      _enabled = automatic['enabled'] == true;
      _paused = automatic['paused'] == true;
      _timeReady = automatic['time_ready'] == true;
      _upload = ClipUploadSnapshot.fromJson({
        ...upload,
        'enabled': automatic['enabled'],
        'paused': automatic['paused']
      });
      _savedSsid = name;
      if (name.isNotEmpty && (forceName || !_nameEdited)) _ssid.text = name;
      if (order == _eventOrder) {
        _network = ClipUploadProtocol.networkLabel(network);
        _checkJob = (network['job'] as num?)?.toInt();
      }
    });
  }

  Future<void> _scanWifi() async {
    if (_blocked) return;
    _setBusy(true);
    setState(() => _scanningWifi = true);
    try {
      final result = await (widget.scanWifi ?? MacWifiScanner.scan)();
      if (!mounted) return;
      setState(() {
        _scan = result;
        _ssid.text = result.targetFor(_ssid.text);
        final count = result.networks.where((n) => n.compatible).length;
        _scanMessage =
            'Mac 当前 Wi-Fi：${result.currentSsid.isEmpty ? '未读取到' : result.currentSsid}。找到 ${result.networks.length} 个网络，$count 个可供 Clip 选择。';
        if (result.currentSsid.isNotEmpty && result.defaultSsid.isEmpty) {
          _scanMessage += ' 当前 Mac 网络不兼容，请选择 2.4 GHz 网络。';
        }
      });
    } on FormatException catch (e) {
      if (mounted) setState(() => _scanMessage = e.message);
    } catch (_) {
      if (mounted) setState(() => _scanMessage = 'Mac Wi-Fi 扫描失败，请检查定位权限后重试。');
    } finally {
      if (mounted) setState(() => _scanningWifi = false);
      _setBusy(false);
      _scheduleRead();
    }
  }

  Future<void> _checkNetwork(AtTransport at) async {
    final accepted = await _send(at, 'AT+NETCHECK');
    final job = (accepted['job'] as num?)?.toInt();
    if (accepted['accepted'] != true || job == null) {
      throw const FormatException('设备未接受网络检测，请重试。');
    }
    _checkJob = job;
    if (mounted) setState(() => _network = '正在检查 Wi-Fi 与 DHCP…');
    final clock = Stopwatch()..start();
    while (clock.elapsed < const Duration(seconds: 65)) {
      await Future<void>.delayed(const Duration(seconds: 1));
      if (!mounted || widget.at != at) return;
      final result = await _send(at, 'AT+NETCHECK?');
      if (result['job'] != job) {
        throw const FormatException('网络检测任务已变化，请重新读取状态。');
      }
      if (mounted) {
        setState(() => _network = ClipUploadProtocol.networkLabel(result));
      }
      if (result['state'] == 'succeeded' && result['cleanup_error'] == 0) {
        if (mounted) {
          setState(
              () => _message = 'Clip Wi-Fi 与 DHCP 检测通过。Server 上传结果请在服务器音频中核实。');
        }
        return;
      }
      if (['failed', 'cancelled', 'succeeded'].contains(result['state'])) {
        throw const FormatException('Wi-Fi 检测未通过，配置已保存，可修改后重试。');
      }
    }
    throw const FormatException('网络检测超时，请重新读取设备状态。');
  }

  Future<void> _saveWifi() => _run((at) async {
        final target = _ssid.text;
        final command = ClipUploadProtocol.wifi(target, _password.text,
            payload: at.mtu.payloadSize);
        final status = await _send(at, 'AT+GSTAT');
        if (status['state'] != 'IDLE' ||
            status['recording'] == true ||
            status['record_pending'] == true ||
            _upload.active) {
          throw const FormatException('请等待 Clip 录音或上传结束后再保存 Wi-Fi。');
        }
        await _send(at, command);
        final saved = await _send(at, 'AT+NETCFG?');
        if (saved['saved'] != true ||
            saved['configured'] != true ||
            ClipUploadProtocol.ssid(saved) != target) {
          throw const FormatException('设备未确认 Wi-Fi 已保存，请重新读取。');
        }
        if (mounted) {
          setState(() {
            _savedSsid = target;
            _message = 'Wi-Fi 已保存，正在测试 Clip 连接…';
          });
        }
        await _checkNetwork(at);
      });
  Future<void> _saveReceiver() => _run((at) async {
        final command = ClipUploadProtocol.receiver(
            _receiver.text.trim(), _device.text.trim(), _token.text.trim(),
            payload: at.mtu.payloadSize);
        await _send(at, 'AT+UPLOADAUTO=off');
        await _send(at, command);
        final saved = await _send(at, 'AT+UPLOADCFG?');
        if (saved['saved'] != true || saved['configured'] != true) {
          throw StateError('not persisted');
        }
        _token.clear();
        if (mounted) setState(() => _message = '上传目标已保存，请检查网络后开启自动上传。');
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
              enabled: !_blocked,
              decoration: InputDecoration(labelText: label)));
  @override
  Widget build(BuildContext context) {
    super.build(context);
    final connected = widget.at != null;
    return Card(
        child: Padding(
            padding: const EdgeInsets.all(20),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.wifi, color: Color(0xff167d8d)),
                const SizedBox(width: 10),
                Expanded(
                    child: Text('Clip Wi-Fi 配网',
                        style: Theme.of(context).textTheme.titleLarge)),
                if (connected)
                  IconButton(
                      tooltip: '刷新上传状态',
                      onPressed: _blocked ? null : () => _run(_read),
                      icon: const Icon(Icons.refresh)),
              ]),
              const SizedBox(height: 12),
              Text(connected
                  ? 'Clip 已保存的 Wi-Fi：${_savedSsid.isEmpty ? '未读取到' : _savedSsid} · 实时联网状态未回报'
                  : '尚未连接 Clip，可先扫描和填写，连接设备后保存测试。'),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                  onPressed: _blocked ? null : _scanWifi,
                  icon: const Icon(Icons.radar),
                  label: Text(_scanningWifi ? '正在扫描…' : '扫描附近 Wi-Fi')),
              const SizedBox(height: 8),
              Text(_scanMessage,
                  style: const TextStyle(color: Color(0xff667085))),
              if (_scan != null) ...[
                const SizedBox(height: 12),
                InputDecorator(
                    decoration: const InputDecoration(labelText: '附近的 Wi-Fi'),
                    child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                      isExpanded: true,
                      value: _scan!.selectionFor(_ssid.text),
                      hint: const Text('选择网络，或手动填写'),
                      items: [
                        for (final n in _scan!.networks)
                          DropdownMenuItem(
                              value: n.ssid,
                              enabled: n.compatible,
                              child: Text(n.label,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                      color:
                                          n.compatible ? null : Colors.grey)))
                      ],
                      onChanged: _blocked
                          ? null
                          : (value) {
                              if (value != null) {
                                setState(() {
                                  _ssid.text = value;
                                  _nameEdited = true;
                                });
                              }
                            },
                    ))),
              ],
              const SizedBox(height: 12),
              TextField(
                  controller: _ssid,
                  enabled: !_blocked,
                  autocorrect: false,
                  decoration: const InputDecoration(labelText: 'Wi-Fi 名称'),
                  onChanged: (_) => setState(() => _nameEdited = true)),
              const SizedBox(height: 12),
              TextField(
                  controller: _password,
                  enabled: !_blocked,
                  obscureText: !_showPassword,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: InputDecoration(
                      labelText: 'Wi-Fi 密码',
                      suffixIcon: IconButton(
                          tooltip: _showPassword ? '隐藏密码' : '显示密码',
                          onPressed: () =>
                              setState(() => _showPassword = !_showPassword),
                          icon: Icon(_showPassword
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined)))),
              const SizedBox(height: 8),
              const Text('保存、测试、扫描与重连后保留输入；密码仅在当前窗口内，不会回读设备密码。',
                  style: TextStyle(fontSize: 12, color: Color(0xff667085))),
              const SizedBox(height: 16),
              Wrap(spacing: 12, runSpacing: 8, children: [
                FilledButton(
                    onPressed: !connected || _blocked || _upload.active
                        ? null
                        : _saveWifi,
                    child: const Text('保存并测试连接')),
                OutlinedButton(
                    onPressed: !connected || _blocked
                        ? null
                        : () => _run((at) async {
                              if (_savedSsid.isNotEmpty &&
                                  _ssid.text != _savedSsid) {
                                throw const FormatException('名称已修改，请先保存并测试连接。');
                              }
                              await _checkNetwork(at);
                            }),
                    child: const Text('重试已保存网络')),
              ]),
              const SizedBox(height: 12),
              Text(_message),
              if (connected) ...[
                const SizedBox(height: 8),
                Text(_network),
                Text(_timeReady ? '设备时间已同步' : '设备时间待同步（上传需有效时间）'),
                const Divider(height: 32),
                Text('联网与自动上传', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(_upload.complete ? '文件上传完成' : '阶段：${_upload.stage}'),
                const SizedBox(height: 8),
                LinearProgressIndicator(value: _upload.progress),
                Text(
                    '已持久确认 ${_upload.confirmed} / ${_upload.size} 字节 · 错误 ${_upload.value['last_error'] ?? 0}'),
                if (_upload.value['delete_after_upload'] == true)
                  const Text('当前固件在整段录音确认上传后清理设备副本。'),
                if ((_upload.value['delete_error'] as num? ?? 0) != 0)
                  const Text('设备副本清理失败，服务器结果不受影响。'),
                SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('自动上传'),
                    subtitle: Text(_paused ? '本次调度已暂停，开启可继续' : '设备空闲时上传'),
                    value: _enabled,
                    onChanged: _blocked
                        ? null
                        : (enabled) => _run((at) async {
                              await _send(at,
                                  'AT+UPLOADAUTO=${enabled ? 'on' : 'off'}');
                              await _read(at);
                            })),
                TextButton(
                    onPressed: _blocked
                        ? null
                        : () => _run((at) async {
                              await _send(at, 'AT+UPLOADCANCEL');
                              await _read(at);
                            }),
                    child: const Text('取消上传并暂停调度')),
                TextButton.icon(
                    onPressed: _blocked || _upload.active
                        ? null
                        : () => _run((at) async {
                              await _send(at,
                                  'AT+TIME=${DateTime.now().millisecondsSinceEpoch ~/ 1000}');
                              await _read(at);
                            }),
                    icon: const Icon(Icons.schedule),
                    label: const Text('同步 Mac 时间到 Clip')),
                ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    title: const Text('Server 与设备凭证'),
                    subtitle: const Text('设备令牌与 App 用户令牌不同'),
                    children: [
                      _field(_receiver, 'Server 主机:端口（DTLS）'),
                      _field(_device, '设备 ID'),
                      _field(_token, '设备令牌', secret: true),
                      const Text('保存时先关闭自动上传；固件需信任 Server 证书且时间有效。'),
                      FilledButton(
                          onPressed:
                              _blocked || _upload.active ? null : _saveReceiver,
                          child: const Text('保存上传目标')),
                    ]),
              ],
              if (_busy)
                const Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: LinearProgressIndicator()),
            ])));
  }
}
