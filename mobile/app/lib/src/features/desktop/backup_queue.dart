import 'dart:async';
import 'dart:convert';
import 'dart:io';
import '../audio_storage/storage_client.dart';
import 'local_library.dart';

class BackupJob {
  final LocalAudio audio;
  final String endpoint;
  final String state;
  final bool manual;
  final int attempts;
  final double progress;
  final String? error;
  final DateTime updatedAt;
  BackupJob(Map<String, dynamic> data)
      : audio = LocalAudio(File(data['path'] as String), data['name'] as String,
            data['bytes'] as int),
        endpoint = data['endpoint'] as String,
        state = data['state'] as String,
        manual = data['manual'] == true,
        attempts = data['attempts'] as int,
        progress = (data['progress'] as num? ?? 0).toDouble(),
        error = data['error'] as String?,
        updatedAt =
            DateTime.fromMillisecondsSinceEpoch(data['updatedAt'] as int? ?? 0);
}

/// Durable single-worker outbox. Credentials and raw server errors never enter it.
class BackupQueue {
  final File file;
  BackupQueue(this.file);
  final Map<String, Map<String, dynamic>> _jobs = {};
  bool running = false;
  String? _activePath;
  Future<void> _writes = Future.value();
  String _key(LocalAudio audio, String endpoint) =>
      '$endpoint|${audio.file.path}';
  int get _now => DateTime.now().millisecondsSinceEpoch;

  Future<void> load() async {
    if (!await file.exists()) return;
    final data = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    for (final entry in data.entries) {
      final job = Map<String, dynamic>.from(entry.value as Map);
      if (job['state'] == 'uploading') job['state'] = 'pending';
      job['manual'] ??= false;
      job['updatedAt'] ??= 0;
      job['progress'] = job['state'] == 'complete' ? 1.0 : 0.0;
      _jobs[entry.key] = job;
    }
  }

  List<BackupJob> jobs({String? endpoint}) {
    final result = _jobs.values
        .where((j) => endpoint == null || j['endpoint'] == endpoint)
        .map((j) => BackupJob(Map<String, dynamic>.from(j)))
        .toList();
    result.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return result;
  }

  Future<void> _save() {
    final snapshot = jsonEncode(_jobs);
    _writes = _writes.catchError((Object _) {}).then((_) async {
      await file.parent.create(recursive: true);
      final temp = File('${file.path}.tmp');
      await temp.writeAsString(snapshot, flush: true);
      await temp.rename(file.path);
    });
    return _writes;
  }

  Future<void> enqueue(LocalAudio audio, String endpoint,
      {bool resetComplete = false}) async {
    final key = _key(audio, endpoint);
    final existing = _jobs[key];
    if (existing != null) {
      if (resetComplete && existing['state'] == 'complete') {
        existing.addAll({
          'state': 'pending',
          'manual': false,
          'attempts': 0,
          'next': 0,
          'progress': 0.0,
          'error': null,
          'updatedAt': _now,
          'name': audio.name
        });
        await _save();
      }
      return;
    }
    _jobs[key] = {
      'path': audio.file.path,
      'name': audio.name,
      'bytes': audio.bytes,
      'endpoint': endpoint,
      'state': 'pending',
      'attempts': 0,
      'next': 0,
      'manual': false,
      'progress': 0.0,
      'updatedAt': _now
    };
    await _save();
  }

  Future<void> requestManual(LocalAudio audio, String endpoint) async {
    await enqueue(audio, endpoint);
    final job = _jobs[_key(audio, endpoint)]!;
    job['manual'] = true;
    if (job['state'] != 'uploading') {
      job.addAll({
        'state': 'pending',
        'attempts': 0,
        'next': 0,
        'progress': 0.0,
        'error': null,
        'name': audio.name,
        'updatedAt': _now
      });
    }
    await _save();
  }

  Future<void> markBackedUp(LocalAudio audio, String endpoint) async {
    await enqueue(audio, endpoint);
    final job = _jobs[_key(audio, endpoint)]!;
    if (job['state'] == 'uploading') return;
    job.addAll({
      'state': 'complete',
      'progress': 1.0,
      'error': null,
      'updatedAt': _now
    });
    await _save();
  }

  void setProgress(LocalAudio audio, String endpoint, double value) {
    final job = _jobs[_key(audio, endpoint)];
    if (job != null && value.isFinite) {
      job['progress'] = value.clamp(0, 1).toDouble();
    }
  }

  String status(LocalAudio audio, String endpoint) {
    final job = _jobs[_key(audio, endpoint)];
    return switch (job?['state']) {
      'complete' => '已备份',
      'uploading' => '上传中',
      'failed' => (job!['attempts'] as int) >= 3 ? '上传失败，请重试' : '失败，等待重试',
      _ => '待备份',
    };
  }

  Future<void> updateName(LocalAudio audio) async {
    for (final job in _jobs.values) {
      if (job['path'] == audio.file.path &&
          job['state'] != 'uploading' &&
          job['state'] != 'complete') {
        job['name'] = audio.name;
      }
    }
    await _save();
  }

  Future<void> removeFile(LocalAudio audio) async {
    if (_activePath == audio.file.path) throw StateError('文件正在上传，请等待完成');
    _jobs.removeWhere((_, job) => job['path'] == audio.file.path);
    await _save();
  }

  Future<void> retryFailed() async {
    for (final job in _jobs.values) {
      if (job['state'] == 'failed') {
        job.addAll(
            {'attempts': 0, 'next': 0, 'state': 'pending', 'error': null});
      }
    }
    await _save();
  }

  String _failure(Object e) {
    if (e is SocketException || e is TimeoutException) return '连接失败，请检查网络和服务地址';
    if (e is FileSystemException) return '文件读写失败，请检查文件、磁盘空间和权限';
    if (e is StorageException) {
      if (e.status == 401 || e.status == 403) return '服务认证失败，请检查访问令牌';
      return e.status == null ? '文件校验或传输失败，请重试' : '服务器返回 ${e.status}，请检查服务状态';
    }
    return '上传失败，请稍后重试';
  }

  Future<void> drain(Future<void> Function(LocalAudio, String) upload,
      {bool Function()? allowed,
      bool Function()? automaticAllowed,
      void Function()? changed,
      String? endpoint}) async {
    if (running) return;
    running = true;
    try {
      for (final entry in _jobs.entries.toList()) {
        final job = entry.value;
        if (!identical(_jobs[entry.key], job)) continue;
        if (endpoint != null && job['endpoint'] != endpoint) continue;
        if (allowed != null && !allowed()) break;
        if (job['manual'] != true &&
            automaticAllowed != null &&
            !automaticAllowed()) {
          continue;
        }
        if (job['state'] == 'complete' ||
            (job['attempts'] as int) >= 3 ||
            (job['next'] as int) > _now) {
          continue;
        }
        _activePath = job['path'] as String;
        job.addAll({
          'state': 'uploading',
          'progress': 0.0,
          'error': null,
          'updatedAt': _now
        });
        await _save();
        changed?.call();
        try {
          await upload(
              LocalAudio(File(job['path'] as String), job['name'] as String,
                  job['bytes'] as int),
              job['endpoint'] as String);
          job.addAll({
            'state': 'complete',
            'progress': 1.0,
            'attempts': 0,
            'error': null
          });
        } catch (e) {
          job['state'] = 'failed';
          job['attempts'] = (job['attempts'] as int) + 1;
          job['next'] = _now + 30000 * (job['attempts'] as int);
          job['error'] = _failure(e);
        }
        job['updatedAt'] = _now;
        _activePath = null;
        await _save();
        changed?.call();
      }
    } finally {
      _activePath = null;
      running = false;
      changed?.call();
    }
  }
}
