import 'dart:io';
import 'dart:ui' show AppExitResponse;
import 'dart:async';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:record/record.dart';
import 'backup_queue.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'server_config.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import '../audio_storage/storage_client.dart';
import 'local_library.dart';
import 'audio_presence.dart';
import 'desktop_clip_page.dart';
import 'audio_dialogs.dart';
import 'recording_drafts.dart';
import 'microphone_access.dart';

class DesktopPage extends StatefulWidget {
  const DesktopPage({super.key});
  @override
  State<DesktopPage> createState() => _DesktopPageState();
}

class _DesktopPageState extends State<DesktopPage> {
  final _address = TextEditingController(text: 'http://127.0.0.1:8765');
  final _token = TextEditingController();
  final _search = TextEditingController();
  final _player = AudioPlayer();
  ServerConfig? _serverConfig;
  AudioRecorder? _audioRecorder;
  AudioRecorder get _recorder => _audioRecorder ??= AudioRecorder();
  final _clock = Stopwatch();
  Timer? _timer;
  BackupQueue? _queue;
  bool _autoBackup = true;
  List<InputDevice> _inputs = [];
  String? _inputId;
  String _inputLabel = '系统默认输入';
  String _activeInput = '';
  StreamSubscription<Amplitude>? _amplitude;
  double _decibels = -60;
  List<File> _drafts = [];
  List<TrashedAudio> _trash = [];
  String? _playingPath;
  RecordingDrafts get _recordings =>
      RecordingDrafts(Directory('${_root!.path}/recordings'));

  bool _recording = false;
  bool _paused = false;
  bool _recordAction = false;
  String? _recordPath;
  String _endpoint = '';
  String _connectedToken = '';
  String _caPath = '';
  String _connectedCaPath = '';
  String get _backupScope => '$_endpoint#account=${_client?.accountKey ?? ''}';
  late final AppLifecycleListener _lifecycle;
  LocalLibrary? _library;
  Directory? _root;
  StorageClient? _client;
  List<LocalAudio> _local = [];
  List<Map<String, dynamic>> _remote = [];
  int _tab = 0;
  bool _clipOpened = false;
  bool _busy = false;
  double? _progress;
  String _status = '本地音频随时可听，连接服务后可以备份和下载。';
  String _playing = '';

  @override
  void initState() {
    super.initState();
    _lifecycle = AppLifecycleListener(onExitRequested: () async {
      if (_recording || _recordAction) {
        if (mounted) setState(() => _status = '请先停止并保存录音，再退出应用。');
        return AppExitResponse.cancel;
      }
      return AppExitResponse.exit;
    });
    _initialize();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_recording && mounted) setState(() {});
      if (DateTime.now().second % 10 == 0) unawaited(_pump());
    });
  }

  Future<void> _initialize() async {
    await _work(() async {
      final dir = await getApplicationSupportDirectory();
      _root = Directory('${dir.path}/boa_desktop');
      _library = LocalLibrary(Directory('${_root!.path}/library'));
      _local = await _library!.list();
      _trash = await _library!.listTrash();
      _drafts = await _recordings.list();
      _queue = BackupQueue(File('${_root!.path}/backup-queue.json'));
      await _queue!.load();
      final settings = File('${_root!.path}/preferences.json');
      if (await settings.exists()) {
        final prefs = jsonDecode(await settings.readAsString()) as Map;
        _autoBackup = prefs['autoBackup'] != false;
        _inputId = prefs['inputId'] as String?;
        _inputLabel = prefs['inputLabel'] as String? ?? '系统默认输入';
      }
      _serverConfig =
          ServerConfig(File('${_root!.path}/credentials/server.json'));
      try {
        final config = await _serverConfig!.read();
        _address.text = config['address'] ?? _address.text;
        _token.text = config['token'] ?? '';
        _caPath = config['caPath'] ?? '';
      } catch (_) {
        _status = '本地服务配置读取失败，请重新填写；音频文件不受影响。';
      }
    });
    if (_token.text.isNotEmpty) {
      await _connect();
    }
  }

  Future<void> _work(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _progress = null;
    });
    try {
      await action();
    } catch (e, stack) {
      debugPrint('Boa desktop operation failed: ${e.runtimeType}\n$stack');
      _status = e is StorageException
          ? e.message
          : e is HandshakeException
              ? 'TLS 验证失败，请检查证书、服务地址和有效期。'
              : e is HttpException || e is SocketException
                  ? '网络连接中断，请重试；未完成下载可继续续传。'
                  : e is FormatException
                      ? e.message
                      : '操作未完成，请检查网络、文件权限或音频格式。';
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _update(double value) {
    if (mounted) setState(() => _progress = value);
  }

  Future<void> _connect() => _work(() async {
        _client?.close();
        _client = null;
        _remote = [];
        final candidate = StorageClient(
            _address.text.trim(), _token.text.trim(),
            caPath: _caPath);
        try {
          final rows = await candidate.list();
          _client = candidate;
          _remote = rows;
          _endpoint = _address.text.trim();
          _connectedToken = _token.text.trim();
          _connectedCaPath = _caPath;
        } catch (_) {
          candidate.close();
          rethrow;
        }
        await _enqueueAll();
        _status = '已连接服务器 · 自动备份${_autoBackup ? '已开启' : '已关闭'}';
        try {
          await _serverConfig!
              .save(_address.text.trim(), _token.text.trim(), caPath: _caPath);
        } catch (_) {
          _status = '已连接；本地配置保存失败，本次配置仅在内存中使用。';
        }
      });

  Future<void> _import() => _work(() async {
        final picked = await FilePicker.platform.pickFiles(
          type: FileType.custom,
          allowedExtensions: ['wav', 'm4a', 'mp3', 'ogg', 'flac', 'aac'],
          withData: false,
        );
        final path = picked?.files.single.path;
        if (path == null) return;
        await _library!.importFile(File(path));
        _local = await _library!.list();
        _tab = 0;
        _status = '导入完成 · 已保存独立副本，原文件保留';
        await _enqueueAll();
      });

  Future<void> _enqueueAll() async {
    if (!_autoBackup || _endpoint.isEmpty || _queue == null) return;
    for (final audio in _local) {
      final hash = audio.file.uri.pathSegments.last.split('.').first;
      if (_remote
          .any((row) => row['sha256'] == hash && row['size'] == audio.bytes)) {
        await _queue!.markBackedUp(audio, _backupScope);
      } else {
        await _queue!.enqueue(audio, _backupScope, resetComplete: true);
      }
    }
    unawaited(_pump());
  }

  Future<void> _pump() async {
    if (_client == null ||
        _connectedToken.isEmpty ||
        _queue == null ||
        _queue!.running ||
        !mounted) {
      return;
    }
    final endpoint = _backupScope;
    final address = _endpoint;
    final caPath = _connectedCaPath;
    final token = _connectedToken;
    try {
      await _queue!.drain(
          (audio, destination) async {
            if (destination != endpoint) {
              throw const FormatException('请连接原备份服务器');
            }
            final client = StorageClient(address, token, caPath: caPath);
            try {
              final uploaded = await client.upload(
                  audio.file, Directory('${_root!.path}/sessions'),
                  filename: audio.name, progress: (value) {
                _queue!.setProgress(audio, destination, value);
                if (mounted) setState(() {});
              });
              if (mounted && _backupScope == destination) {
                setState(() {
                  _remote.removeWhere((r) => r['id'] == uploaded['id']);
                  _remote.add(uploaded);
                });
              }
            } finally {
              client.close();
            }
          },
          endpoint: endpoint,
          allowed: () => mounted && _backupScope == endpoint,
          automaticAllowed: () => _autoBackup,
          changed: () {
            if (mounted) setState(() {});
          });
    } catch (_) {
      if (mounted) setState(() => _status = '备份队列无法保存，请检查磁盘空间；原文件保留。');
    }
  }

  Future<void> _upload(LocalAudio audio) => _work(() async {
        if (_queue == null || _client == null) return;
        _remote = await _client!.list();
        final hash = audio.file.uri.pathSegments.last.split('.').first;
        if (_remote
            .any((r) => r['sha256'] == hash && r['size'] == audio.bytes)) {
          await _queue!.markBackedUp(audio, _backupScope);
          _status = '服务器已有相同音频，无需重复上传';
        } else {
          await _queue!.requestManual(audio, _backupScope);
          _status = '已加入手动上传任务';
          unawaited(_pump());
        }
      });

  Future<void> _savePreferences() async {
    final file = File('${_root!.path}/preferences.json');
    await file.parent.create(recursive: true);
    await file.writeAsString(
        jsonEncode({
          'autoBackup': _autoBackup,
          'inputId': _inputId,
          'inputLabel': _inputLabel
        }),
        flush: true);
  }

  Future<void> _toggleBackup(bool enabled) => _work(() async {
        _autoBackup = enabled;
        await _savePreferences();
        await _enqueueAll();
        _status = enabled ? '自动上传已开启' : '自动上传已关闭；手动任务和已开始的上传仍会继续';
      });

  Future<void> _microphonePermission({bool request = false}) {
    final recorder = _recorder;
    return requireMicrophonePermission(
        (prompt) => recorder.hasPermission(request: prompt),
        request: request, stalled: () {
      if (identical(_audioRecorder, recorder)) _audioRecorder = null;
      unawaited(recorder.dispose().catchError((Object _) {}));
    });
  }

  Future<void> _loadInputs() => _work(() async {
        setState(() => _status = '正在检查麦克风权限…');
        await _microphonePermission();
        setState(() => _status = '正在读取系统输入设备…');
        _inputs = await _recorder.listInputDevices();
        _status = '已读取 ${_inputs.length} 个麦克风输入';
      });

  Future<void> _startRecording() async {
    if (_busy || _recordAction || _recording || _root == null) return;
    setState(() => _recordAction = true);
    try {
      await _microphonePermission(request: true);
      await _player.stop();
      _inputs = await _recorder.listInputDevices();
      final selected = _inputs.where((d) => d.id == _inputId).firstOrNull;
      _activeInput = selected?.label ?? '系统默认输入';
      final fallback = _inputId != null && selected == null;
      final dir = Directory('${_root!.path}/recordings');
      await dir.create(recursive: true);
      _recordPath =
          '${dir.path}/录音-${DateTime.now().millisecondsSinceEpoch}.wav';
      await _recorder.start(
          RecordConfig(
              encoder: AudioEncoder.wav,
              sampleRate: 44100,
              numChannels: 1,
              device: selected),
          path: _recordPath!);
      _clock.reset();
      _clock.start();
      _recording = true;
      _paused = false;
      _status = fallback ? '原麦克风不可用，本次使用系统默认输入' : '麦克风录音中 · 停止后命名保存';
      await _amplitude?.cancel();
      _amplitude = _recorder
          .onAmplitudeChanged(const Duration(milliseconds: 200))
          .listen((value) {
        if (mounted && _recording && !_paused) {
          setState(() => _decibels = value.current);
        }
      }, onError: (Object _) {});
    } catch (e) {
      _status = e is FormatException ? e.message : '无法启动麦克风，请检查系统权限和输入设备';
    } finally {
      if (mounted) setState(() => _recordAction = false);
    }
  }

  Future<void> _pauseRecording() async {
    if (_recordAction) return;
    setState(() => _recordAction = true);
    try {
      if (_paused) {
        await _recorder.resume();
        _clock.start();
      } else {
        await _recorder.pause();
        _clock.stop();
      }
      _paused = !_paused;
    } catch (_) {
      _status = '暂停/继续失败，请重试或停止保存';
    } finally {
      if (mounted) setState(() => _recordAction = false);
    }
  }

  Future<void> _stopRecording() async {
    if (_recordAction) return;
    setState(() => _recordAction = true);
    try {
      final path = await _recorder.stop() ?? _recordPath;
      _clock.stop();
      _recording = false;
      _paused = false;
      if (path == null || await File(path).length() <= 44) {
        throw const FormatException('没有收到有效音频，请检查麦克风输入');
      }
      await _amplitude?.cancel();
      await _saveDraft(File(path), durationMs: _clock.elapsedMilliseconds);
      _recordPath = null;
    } catch (e) {
      _status = e is FormatException ? e.message : '保存失败，录音暂存文件已保留，请检查磁盘空间';
    } finally {
      if (_root != null) _drafts = await _recordings.list();
      if (mounted) setState(() => _recordAction = false);
    }
  }

  Future<void> _recoverRecording() => _work(() async {
        final file = _drafts.length == 1
            ? _drafts.first
            : await showDialog<File>(
                context: context,
                builder: (context) =>
                    SimpleDialog(title: const Text('恢复暂存录音'), children: [
                      for (final draft in _drafts)
                        SimpleDialogOption(
                            onPressed: () => Navigator.pop(context, draft),
                            child: Text(draft.uri.pathSegments.last))
                    ]));
        if (file != null) await _saveDraft(file);
      });

  Future<void> _saveDraft(File file, {int? durationMs}) async {
    if (!mounted) return;
    final name = await askAudioName(context,
        title: '保存录音',
        initial:
            '录音-${DateTime.now().toLocal().toString().split('.').first.replaceAll(':', '-')}',
        extension: 'wav',
        hint: '取消会保留暂存录音，可稍后恢复保存。');
    if (name == null) {
      _status = '录音已暂存，点击“恢复录音”继续保存';
      return;
    }
    await _recordings.save(file, _library!, name: name, durationMs: durationMs);
    _local = await _library!.list();
    _drafts = await _recordings.list();
    _tab = 0;
    _status = '录音已保存到本地音频库';
    await _enqueueAll();
  }

  Future<void> _download(Map<String, dynamic> row) => _work(() async {
        String? rawTarget;
        if (row['source'] == 'clip_direct') {
          rawTarget = await FilePicker.platform.saveFile(
              dialogTitle: '保存 Clip 原始录音', fileName: row['filename'] as String);
          if (rawTarget == null) return;
        }
        _status = '正在下载 ${row['filename']}';
        final downloaded = await _client!.download(
            row, Directory('${_root!.path}/downloads/${_client!.accountKey}'),
            progress: _update);
        if (rawTarget != null) {
          final target = File(rawTarget);
          if (target.absolute.path.startsWith('${_root!.absolute.path}/')) {
            throw const FormatException('请选择应用数据目录之外的位置');
          }
          await downloaded.copy(target.path);
          if (await StorageClient.hash(target) != row['sha256']) {
            throw const FormatException('导出校验失败，请重试');
          }
          _status = 'Clip 原始录音已保存（需转换后播放）';
          return;
        }
        final imported = await _library!.importFile(downloaded,
            name: row['filename'] as String, source: 'download');
        await _queue?.markBackedUp(imported, _backupScope);
        _local = await _library!.list();
        // Only the duplicate staging copy is removed after verified local import.
        await downloaded.delete();
        _status = '下载完成 · 已保存到本地音频库';
      });

  Future<void> _play(LocalAudio audio) => _work(() async {
        await _player.stop();
        await _player.setFilePath(audio.file.path);
        _playing = audio.name;
        _playingPath = audio.file.path;
        _status = '正在播放 ${audio.name}';
        _startPlayback();
      });

  void _startPlayback() {
    _player.play().catchError((Object _) {
      if (mounted) setState(() => _status = '播放器无法读取此音频，请检查格式。');
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _lifecycle.dispose();
    _amplitude?.cancel();
    _audioRecorder?.dispose();
    _client?.close();
    _player.dispose();
    _address.dispose();
    _token.dispose();
    _search.dispose();
    super.dispose();
  }

  String _size(int bytes) => '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
  String _time(Duration value) {
    final seconds = value.inSeconds;
    return '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')}';
  }

  Widget _empty(IconData icon, String title, String detail) => Center(
          child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 56, color: const Color(0xff167d8d)),
          const SizedBox(height: 18),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(detail, textAlign: TextAlign.center),
        ],
      ));

  Widget _files() {
    final query = _search.text.toLowerCase();
    if (_tab == 0) {
      final rows =
          _local.where((r) => r.name.toLowerCase().contains(query)).toList();
      if (rows.isEmpty) {
        return _empty(
            Icons.library_music_outlined,
            query.isEmpty ? '你的音频工作台' : '没有找到匹配音频',
            query.isEmpty ? '点击“导入音频”，开始在 Mac 上整理和回听。' : '换个关键词试试。');
      }
      return ListView.separated(
          itemCount: rows.length,
          separatorBuilder: (_, __) => const SizedBox(height: 8),
          itemBuilder: (_, i) {
            final row = rows[i];
            return Card(
                elevation: 0,
                color: Colors.white,
                child: ListTile(
                  leading: const CircleAvatar(
                      child: Icon(Icons.audio_file_outlined)),
                  title: Text(row.name,
                      maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text(
                      '${localPresence(row, _remote, connected: _client != null)} · ${_size(row.bytes)} · 入库 ${audioTime(row.addedAt)}\n ${_endpoint.isEmpty ? '待配置备份' : _queue?.status(row, _backupScope) ?? '待备份'}'),
                  onTap: () => showAudioDetails(context, row,
                      presence: localPresence(row, _remote,
                          connected: _client != null)),
                  trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                    IconButton(
                        tooltip: '播放',
                        onPressed:
                            _busy || _recording ? null : () => _play(row),
                        icon: const Icon(Icons.play_arrow)),
                    IconButton(
                        tooltip: '手动上传（无需开启自动上传）',
                        onPressed: _busy || _client == null
                            ? null
                            : () => _upload(row),
                        icon: const Icon(Icons.cloud_upload_outlined)),
                    PopupMenuButton<String>(
                        tooltip: '管理音频',
                        enabled: !_busy,
                        onSelected: (action) => _manage(row, action),
                        itemBuilder: (_) => const [
                              PopupMenuItem(
                                  value: 'rename', child: Text('重命名')),
                              PopupMenuItem(
                                  value: 'export', child: Text('导出文件…')),
                              PopupMenuItem(
                                  value: 'trash', child: Text('移入回收站')),
                            ]),
                  ]),
                ));
          });
    }
    final rows = _remote
        .where((r) => (r['filename'] as String).toLowerCase().contains(query))
        .toList()
      ..sort((a, b) => remoteTime(b).compareTo(remoteTime(a)));
    if (_client == null) {
      return _empty(Icons.cloud_outlined, '连接你的音频服务器', '在“服务设置”填写地址和令牌，然后连接。');
    }
    if (rows.isEmpty) {
      return _empty(
          Icons.cloud_done_outlined, '暂无匹配的服务器音频', '从本地音频库上传，或清除搜索条件。');
    }
    return ListView.builder(
        itemCount: rows.length,
        itemBuilder: (_, i) {
          final row = rows[i];
          return Card(
              elevation: 0,
              color: Colors.white,
              child: ListTile(
                leading: const Icon(Icons.cloud_done_outlined),
                title: Text(row['filename'] as String,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(
                    '${row['source'] == 'clip_direct' ? 'Clip · 原始录音' : 'App 上传'} · ${remotePresence(row, _local)} · ${_size(row['size'] as int)}\n上传 ${audioTime(remoteTime(row))}'),
                trailing: IconButton(
                    tooltip: '下载到本地',
                    onPressed: _busy ? null : () => _download(row),
                    icon: const Icon(Icons.download_outlined)),
              ));
        });
  }

  Future<void> _manage(LocalAudio audio, String action) => _work(() async {
        if (action == 'rename') {
          final name = await askAudioName(context,
              title: '重命名',
              initial: audio.name.replaceFirst(RegExp(r'\.[^.]+$'), ''),
              extension: audio.extension,
              hint: '修改本地显示名称；已上传的服务器文件名称保留。');
          if (name == null) return;
          final renamed = await _library!.rename(audio, name);
          await _queue?.updateName(renamed);
          if (_playingPath == audio.file.path) _playing = renamed.name;
          _status = '本地音频已重命名';
        } else if (action == 'export') {
          final path = await FilePicker.platform.saveFile(
              dialogTitle: '导出音频',
              fileName: audio.name,
              type: FileType.custom,
              allowedExtensions: [audio.extension]);
          if (path == null) return;
          await _library!.export(audio, File(path));
          _status = '导出完成 · 文件字节校验通过';
        } else if (action == 'trash') {
          if (_queue!.jobs().any((j) =>
              j.audio.file.path == audio.file.path && j.state == 'uploading')) {
            throw const FormatException('文件正在上传，请等待完成后再移入回收站');
          }
          final confirmed = await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                      title: const Text('移入回收站？'),
                      content: Text('${audio.name}\n可随时恢复。服务器上的副本保留。'),
                      actions: [
                        TextButton(
                            onPressed: () => Navigator.pop(context, false),
                            child: const Text('取消')),
                        FilledButton(
                            onPressed: () => Navigator.pop(context, true),
                            child: const Text('移入回收站'))
                      ]));
          if (confirmed != true) return;
          if (_playingPath == audio.file.path) {
            await _player.stop();
            _playing = '';
            _playingPath = null;
          }
          await _queue!.removeFile(audio);
          await _library!.moveToTrash(audio);
          _trash = await _library!.listTrash();
          _status = '已移入回收站 · 服务器副本保留';
        }
        _local = await _library!.list();
      });

  Widget _trashView() {
    if (_trash.isEmpty) {
      return _empty(Icons.delete_outline, '回收站为空', '本地删除的音频会保留在这里，可随时恢复。');
    }
    return ListView(children: [
      for (final item in _trash)
        Card(
            child: ListTile(
                leading: const Icon(Icons.audio_file_outlined),
                title: Text(item.audio.name),
                subtitle: Text(
                    '${_size(item.audio.bytes)} · 移入 ${audioTime(item.deletedAt)}'),
                trailing: TextButton(
                    onPressed: _busy
                        ? null
                        : () => _work(() async {
                              await _library!.restore(item);
                              _local = await _library!.list();
                              _trash = await _library!.listTrash();
                              await _enqueueAll();
                              _status = '音频已恢复，原始时间和来源保留';
                            }),
                    child: const Text('恢复'))))
    ]);
  }

  Widget _tasks() {
    final jobs = _queue?.jobs() ?? [];
    if (jobs.isEmpty) {
      return _empty(Icons.sync, '暂无同步任务', '连接服务器后开启自动上传，或在本地音频旁点击上传。');
    }
    return ListView(children: [
      Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child:
              Text(_autoBackup ? '自动上传已开启 · 任务按顺序处理' : '自动上传已关闭 · 手动任务仍可执行')),
      for (final job in jobs)
        Card(
            child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Expanded(
                            child: Text(job.audio.name,
                                maxLines: 1, overflow: TextOverflow.ellipsis)),
                        Text(_jobState(job)),
                        const SizedBox(width: 12),
                        TextButton(
                            onPressed: _busy ||
                                    _client == null ||
                                    job.endpoint != _backupScope ||
                                    job.state == 'uploading'
                                ? null
                                : () => _upload(job.audio),
                            child: Text(
                                job.state == 'complete' ? '检查副本' : '上传 / 重试'))
                      ]),
                      Text(
                          '${job.manual ? '手动' : '自动'} · ${job.endpoint.split('#').first}',
                          style: const TextStyle(color: Color(0xff667085))),
                      if (job.state == 'uploading') ...[
                        const SizedBox(height: 8),
                        LinearProgressIndicator(value: job.progress),
                        Text('${(job.progress * 100).toStringAsFixed(0)}%')
                      ],
                      if (job.error != null)
                        Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                                '${job.error} · 已尝试 ${job.attempts}/3 次',
                                style:
                                    const TextStyle(color: Color(0xffb54708)))),
                    ]))),
    ]);
  }

  String _jobState(BackupJob job) => job.endpoint != _backupScope &&
          job.state != 'complete' &&
          job.state != 'uploading'
      ? '等待连接原服务器'
      : switch (job.state) {
          'complete' => '已备份',
          'uploading' => '上传中',
          'failed' => job.attempts >= 3 ? '失败 · 等待手动重试' : '失败 · 稍后重试',
          _ => job.endpoint != _backupScope
              ? '等待连接原服务器'
              : !_autoBackup && !job.manual
                  ? '自动任务已暂停'
                  : '等待上传',
        };

  Future<void> _importCa() => _work(() async {
        final selection = await FilePicker.platform.pickFiles(
            type: FileType.custom,
            allowedExtensions: ['pem', 'crt'],
            withData: false);
        final source = selection?.files.single.path;
        if (source == null) return;
        final file = File(source);
        if (await file.length() > 256 * 1024) {
          throw const FormatException('证书文件过大');
        }
        final bytes = await file.readAsBytes();
        SecurityContext(withTrustedRoots: true)
            .setTrustedCertificatesBytes(bytes);
        final directory = Directory('${_root!.path}/credentials');
        await directory.create(recursive: true);
        final target =
            File('${directory.path}/ca-${sha256.convert(bytes)}.pem');
        await target.writeAsBytes(bytes, flush: true);
        _caPath = target.path;
        _status = '证书已导入，点击“连接并保存”生效。';
      });

  Widget _settings() => ListView(children: [
        Text('录音输入', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        Text('已选：$_inputLabel'),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
            initialValue: _inputs.any((d) => d.id == _inputId) ? _inputId : '',
            key: ValueKey(
                '${_inputId ?? ''}:${_inputs.map((d) => d.id).join(',')}'),
            decoration: const InputDecoration(labelText: '麦克风'),
            items: [
              const DropdownMenuItem(value: '', child: Text('系统默认输入')),
              for (final d in _inputs)
                DropdownMenuItem(value: d.id, child: Text(d.label))
            ],
            onChanged: _recording || _recordAction || _busy
                ? null
                : (id) => _work(() async {
                      _inputId = id == '' ? null : id;
                      _inputLabel =
                          _inputs.where((d) => d.id == id).firstOrNull?.label ??
                              '系统默认输入';
                      await _savePreferences();
                    })),
        Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
                onPressed:
                    _busy || _recordAction || _recording ? null : _loadInputs,
                icon: const Icon(Icons.refresh),
                label: const Text('刷新麦克风列表'))),
        const Text('已选设备离线时会使用系统默认输入，并在录音时提示。'),
        const SizedBox(height: 28),
        Text('连接自有存储', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        const Text('本机服务使用 127.0.0.1；其他电脑使用服务器地址。\n音频保存在应用本地目录，关闭服务仍可播放。'),
        const SizedBox(height: 16),
        SwitchListTile(
            title: const Text('自动上传备份'),
            subtitle: const Text('连接后自动上传现有音频、新录音和导入文件；原件保留。应用退出时暂停，下次打开继续。'),
            value: _autoBackup,
            onChanged: _busy || _root == null ? null : _toggleBackup),
        const SizedBox(height: 24),
        TextField(
            controller: _address,
            enabled: !_busy && !(_queue?.running ?? false),
            decoration: const InputDecoration(labelText: '服务地址')),
        const SizedBox(height: 16),
        TextField(
            controller: _token,
            enabled: !_busy && !(_queue?.running ?? false),
            obscureText: true,
            decoration: const InputDecoration(
                labelText: '访问令牌', helperText: '保存在 App 沙箱文件中，不加密，仅当前用户可读')),
        const SizedBox(height: 16),
        Text(_caPath.isEmpty ? '证书：系统信任' : '证书：系统信任 + 已导入的开发证书'),
        Wrap(spacing: 12, children: [
          TextButton.icon(
              onPressed: _busy || (_queue?.running ?? false) ? null : _importCa,
              icon: const Icon(Icons.verified_user_outlined),
              label: const Text('导入 CA / 开发证书')),
          if (_caPath.isNotEmpty)
            TextButton(
                onPressed: _busy || (_queue?.running ?? false)
                    ? null
                    : () => setState(() => _caPath = ''),
                child: const Text('恢复系统信任')),
        ]),
        const Text('仅导入你确认过的 PEM 证书；导入后重新连接。仍会验证证书和主机名。'),
        const SizedBox(height: 20),
        Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
                onPressed:
                    _busy || (_queue?.running ?? false) ? null : _connect,
                icon: const Icon(Icons.link),
                label: const Text('连接并保存'))),
        const SizedBox(height: 32),
        const Text('当前版本', style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        const Text(
            'Mac 音频工作台 · Beta 1.0.1-beta.4\n支持本地导入、播放、HTTP 备份与下载。\n支持麦克风录音和自动备份；Clip 配网、上传管理和录音控制见“Clip 设备”。'),
      ]);

  Widget _playbar() => Container(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
        decoration: const BoxDecoration(
            color: Colors.white,
            border: Border(top: BorderSide(color: Color(0xffe4e7ec)))),
        child: Row(children: [
          StreamBuilder<PlayerState>(
              stream: _player.playerStateStream,
              builder: (_, snapshot) => IconButton.filled(
                  tooltip: snapshot.data?.playing == true ? '暂停' : '播放',
                  onPressed: _playing.isEmpty || _recording
                      ? null
                      : () async {
                          if (_player.playing) {
                            await _player.pause();
                          } else {
                            if (_player.processingState ==
                                ProcessingState.completed) {
                              await _player.seek(Duration.zero);
                            }
                            _startPlayback();
                          }
                        },
                  icon: Icon(snapshot.data?.playing == true
                      ? Icons.pause
                      : Icons.play_arrow))),
          const SizedBox(width: 16),
          SizedBox(
              width: 180,
              child: Text(_playing.isEmpty ? '选择一段音频开始播放' : _playing,
                  maxLines: 2, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 16),
          Expanded(
              child: StreamBuilder<Duration>(
                  stream: _player.positionStream,
                  builder: (_, snapshot) {
                    final duration = _player.duration ?? Duration.zero;
                    final position = snapshot.data ?? Duration.zero;
                    final max = duration.inMilliseconds.toDouble();
                    return Row(children: [
                      Text(_time(position)),
                      Expanded(
                          child: Slider(
                        value: position.inMilliseconds
                            .toDouble()
                            .clamp(0, max > 0 ? max : 1),
                        max: max > 0 ? max : 1,
                        onChanged: max == 0
                            ? null
                            : (v) =>
                                _player.seek(Duration(milliseconds: v.toInt())),
                      )),
                      Text(_time(duration))
                    ]);
                  })),
        ]),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
          body: Column(children: [
        Expanded(
            child: Row(children: [
          SizedBox(
              width: 200,
              child: Material(
                  color: const Color(0xffedf2f3),
                  child: Column(children: [
                    const Padding(
                        padding: EdgeInsets.fromLTRB(20, 30, 20, 28),
                        child: Row(children: [
                          Icon(Icons.graphic_eq, color: Color(0xff167d8d)),
                          SizedBox(width: 8),
                          Flexible(
                              child: Text('Boa Voice',
                                  style: TextStyle(
                                      fontSize: 21,
                                      fontWeight: FontWeight.w700))),
                        ])),
                    for (final item in [
                      (Icons.library_music_outlined, '本地音频'),
                      (Icons.cloud_outlined, '服务器音频'),
                      (Icons.tune, '服务设置'),
                      (Icons.bluetooth, 'Clip 设备'),
                      (Icons.sync, '同步任务'),
                      (Icons.delete_outline, '回收站')
                    ].asMap().entries)
                      Padding(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 4),
                          child: ListTile(
                            selected: _tab == item.key,
                            selectedTileColor: const Color(0xffd6e9e9),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12)),
                            leading: Icon(item.value.$1),
                            title: Text(item.value.$2),
                            onTap: () => setState(() {
                              _tab = item.key;
                              if (_tab == 3) _clipOpened = true;
                              _search.clear();
                            }),
                          )),
                    const Spacer(),
                    const Padding(
                        padding: EdgeInsets.all(20),
                        child: Text('个人音频工作台\nmacOS · 本地优先',
                            style: TextStyle(color: Color(0xff667085)))),
                  ]))),
          Expanded(
              child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                              child: Text(
                                  [
                                    '本地音频',
                                    '服务器音频',
                                    '服务设置',
                                    'Clip 设备',
                                    '同步任务',
                                    '回收站'
                                  ][_tab],
                                  style: const TextStyle(
                                      fontSize: 28,
                                      fontWeight: FontWeight.bold))),
                          if (_tab == 1)
                            IconButton(
                                tooltip: '刷新服务器',
                                onPressed: _busy ||
                                        _client == null ||
                                        (_queue?.running ?? false)
                                    ? null
                                    : _connect,
                                icon: const Icon(Icons.refresh)),
                          FilledButton.icon(
                              onPressed: _busy ||
                                      _recordAction ||
                                      _root == null ||
                                      _recording
                                  ? null
                                  : _startRecording,
                              icon: const Icon(Icons.mic),
                              label: const Text('麦克风录音')),
                          const SizedBox(width: 12),
                          FilledButton.icon(
                              onPressed:
                                  _busy || _library == null ? null : _import,
                              icon: const Icon(Icons.add),
                              label: const Text('导入音频')),
                        ]),
                        const SizedBox(height: 20),
                        if (_tab < 2) ...[
                          TextField(
                              controller: _search,
                              onChanged: (_) => setState(() {}),
                              decoration: const InputDecoration(
                                  prefixIcon: Icon(Icons.search),
                                  hintText: '搜索音频名称 · 时间从新到旧')),
                          const SizedBox(height: 20),
                        ],
                        if (_recording)
                          Card(
                              color: const Color(0xffffe9e8),
                              child: Padding(
                                  padding: const EdgeInsets.all(12),
                                  child: Row(children: [
                                    const Icon(Icons.mic, color: Colors.red),
                                    const SizedBox(width: 12),
                                    Expanded(
                                        child: Text(
                                            '${_paused ? '已暂停' : '正在录音'}  ${_time(_clock.elapsed)} · $_activeInput')),
                                    SizedBox(
                                        width: 100,
                                        child: Column(children: [
                                          LinearProgressIndicator(
                                              value: _paused
                                                  ? 0
                                                  : ((_decibels + 60) / 60)
                                                      .clamp(0, 1)),
                                          Text(
                                              _paused
                                                  ? '输入已暂停'
                                                  : '${_decibels.isFinite ? _decibels.toStringAsFixed(0) : '—'} dBFS',
                                              style: const TextStyle(
                                                  fontSize: 11)),
                                        ])),
                                    const SizedBox(width: 12),
                                    TextButton(
                                        onPressed: _recordAction
                                            ? null
                                            : _pauseRecording,
                                        child: Text(_paused ? '继续' : '暂停')),
                                    FilledButton(
                                        onPressed: _recordAction
                                            ? null
                                            : _stopRecording,
                                        child: const Text('停止并保存')),
                                  ]))),
                        if (_drafts.isNotEmpty && !_recording)
                          Card(
                              child: ListTile(
                                  leading: const Icon(Icons.restore),
                                  title: Text('${_drafts.length} 段未保存的暂存录音'),
                                  subtitle: const Text('上次取消保存或应用异常退出后保留'),
                                  trailing: TextButton(
                                      onPressed: _busy || _recordAction
                                          ? null
                                          : _recoverRecording,
                                      child: const Text('恢复录音')))),
                        Expanded(
                            child: IndexedStack(
                                index: _tab == 3 ? 1 : 0,
                                children: [
                              switch (_tab) {
                                2 => _settings(),
                                4 => _tasks(),
                                5 => _trashView(),
                                _ => _files()
                              },
                              _clipOpened
                                  ? DesktopClipPage(
                                      serverAddress: _address.text.trim())
                                  : const SizedBox.shrink(),
                            ])),
                        const SizedBox(height: 16),
                        if (_busy) LinearProgressIndicator(value: _progress),
                        const SizedBox(height: 8),
                        Text(_status,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: Color(0xff667085))),
                      ]))),
        ])),
        _playbar(),
      ]));
}
