import 'dart:convert';
import 'dart:io';
import 'package:path/path.dart' as p;
import '../audio_storage/storage_client.dart';

class LocalAudio {
  final File file;
  final String name;
  final int bytes;
  final DateTime addedAt;
  final String source;
  final int? durationMs;
  LocalAudio(this.file, this.name, this.bytes,
      {DateTime? addedAt, this.source = 'unknown', this.durationMs})
      : addedAt = addedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
  String get extension => p.extension(file.path).substring(1).toLowerCase();
}

class TrashedAudio {
  final Directory directory;
  final String originalFileName;
  final LocalAudio audio;
  final DateTime deletedAt;
  TrashedAudio(
      this.directory, this.originalFileName, this.audio, this.deletedAt);
}

String audioDisplayName(String input, String extension) {
  final value = input.trim();
  if (value.isEmpty ||
      value == '.' ||
      value == '..' ||
      value.contains(RegExp(r'[/\\\x00-\x1f\x7f]'))) {
    throw const FormatException('名称不能为空，也不能包含路径或控制字符');
  }
  final result =
      value.toLowerCase().endsWith('.$extension') ? value : '$value.$extension';
  if (utf8.encode(result).length > 240) {
    throw const FormatException('名称过长，请缩短后重试');
  }
  return result;
}

/// Private copies and metadata; deletion is recoverable and never affects the server.
class LocalLibrary {
  final Directory root;
  LocalLibrary(this.root);
  Directory get trashRoot => Directory(p.join(root.parent.path, 'trash'));
  static final _fileName =
      RegExp(r'^[a-f0-9]{64}\.(wav|m4a|mp3|ogg|flac|aac)$');

  void _check(LocalAudio audio) {
    if (!p.equals(p.normalize(audio.file.parent.absolute.path),
            p.normalize(root.absolute.path)) ||
        !_fileName.hasMatch(p.basename(audio.file.path))) {
      throw const FormatException('请选择音频库中的文件');
    }
  }

  Future<Map<String, dynamic>> _metadata(File file) async {
    try {
      final value = jsonDecode(await File('${file.path}.json').readAsString());
      if (value is Map) return Map<String, dynamic>.from(value);
    } on FileSystemException {
      // Interrupted sidecars must not hide the committed audio bytes.
    } on FormatException {
      // Damaged metadata falls back to file information.
    }
    return {};
  }

  Map<String, dynamic> _serialize(LocalAudio a) => {
        'name': a.name,
        'addedAt': a.addedAt.toUtc().toIso8601String(),
        'source': a.source,
        if (a.durationMs != null) 'durationMs': a.durationMs,
      };
  Future<void> _save(File file, Map<String, dynamic> data) async {
    final temp = File('${file.path}.json.part');
    await temp.writeAsString(jsonEncode(data), flush: true);
    await temp.rename('${file.path}.json');
  }

  Future<LocalAudio> _read(File file, [Map<String, dynamic>? metadata]) async {
    final data = metadata ?? await _metadata(file);
    final duration = data['durationMs'];
    return LocalAudio(
        file,
        data['name'] is String ? data['name'] as String : p.basename(file.path),
        await file.length(),
        addedAt: DateTime.tryParse(data['addedAt']?.toString() ?? '') ??
            (await file.stat()).modified,
        source: data['source'] is String ? data['source'] as String : 'unknown',
        durationMs: duration is int && duration > 0 ? duration : null);
  }

  Future<LocalAudio> importFile(File input,
      {String? name, String source = 'import', int? durationMs}) async {
    final title = name ?? p.basename(input.path);
    final extension = title.split('.').last.toLowerCase();
    if (!['wav', 'm4a', 'mp3', 'ogg', 'flac', 'aac'].contains(extension)) {
      throw const FormatException('请选择 WAV、M4A、MP3、Ogg、FLAC 或 AAC 音频');
    }
    final size = await input.length();
    if (size == 0) throw const FormatException('不能导入空文件');
    await root.create(recursive: true);
    final hash = await StorageClient.hash(input);
    final target = File(p.join(root.path, '$hash.$extension'));
    if (await target.exists() && await StorageClient.hash(target) == hash) {
      return _read(target);
    }
    final partial = File('${target.path}.part');
    try {
      await input.copy(partial.path);
      if (await StorageClient.hash(partial) != hash) {
        throw const FormatException('导入期间文件发生变化，请重试');
      }
      await partial.rename(target.path);
      final audio = LocalAudio(target, title, size,
          addedAt: DateTime.now().toUtc(),
          source: source,
          durationMs: durationMs);
      await _save(target, _serialize(audio));
      return audio;
    } finally {
      if (await partial.exists()) await partial.delete();
    }
  }

  Future<List<LocalAudio>> list() async {
    if (!await root.exists()) return [];
    final rows = <LocalAudio>[];
    await for (final entity in root.list()) {
      if (entity is File && _fileName.hasMatch(p.basename(entity.path))) {
        rows.add(await _read(entity));
      }
    }
    rows.sort((a, b) {
      final time = b.addedAt.compareTo(a.addedAt);
      return time != 0 ? time : a.file.path.compareTo(b.file.path);
    });
    return rows;
  }

  Future<LocalAudio> rename(LocalAudio audio, String input) async {
    _check(audio);
    final name = audioDisplayName(input, audio.extension);
    final current = await _read(audio.file);
    final data = _serialize(current)..['name'] = name;
    await _save(audio.file, data);
    return _read(audio.file, data);
  }

  Future<void> export(LocalAudio audio, File destination) async {
    _check(audio);
    // Export must never overwrite any private app data, including via a symlink.
    final privateRoot = await root.parent.resolveSymbolicLinks();
    final lexicalTarget = p.normalize(destination.absolute.path);
    final resolvedTarget = await destination.exists()
        ? await destination.resolveSymbolicLinks()
        : p.join(await destination.parent.resolveSymbolicLinks(),
            p.basename(destination.path));
    if (p.isWithin(p.normalize(root.parent.absolute.path), lexicalTarget) ||
        p.isWithin(privateRoot, resolvedTarget) ||
        privateRoot == resolvedTarget) {
      throw const FormatException('请选择应用私有目录之外的导出位置，例如桌面或下载文件夹');
    }
    if (p.equals(p.normalize(audio.file.absolute.path),
            p.normalize(destination.absolute.path)) ||
        (await destination.exists() &&
            await FileSystemEntity.identical(
                audio.file.path, destination.path))) {
      throw const FormatException('请选择音频库之外的导出位置');
    }
    await audio.file.copy(destination.path);
    if (await destination.length() != await audio.file.length() ||
        await StorageClient.hash(destination) !=
            p.basename(audio.file.path).split('.').first) {
      throw const FormatException('导出校验失败，请重试；音频库原件保留');
    }
  }

  Future<TrashedAudio> moveToTrash(LocalAudio audio) async {
    _check(audio);
    final current = await _read(audio.file);
    final deletedAt = DateTime.now().toUtc();
    final folder = Directory(p.join(trashRoot.path,
        '${deletedAt.microsecondsSinceEpoch}-${p.basename(audio.file.path)}'));
    await folder.create(recursive: true);
    final manifest = File(p.join(folder.path, 'record.json'));
    await manifest.writeAsString(
        jsonEncode({
          ..._serialize(current),
          'originalFileName': p.basename(audio.file.path),
          'deletedAt': deletedAt.toIso8601String(),
        }),
        flush: true);
    final moved = await audio.file
        .rename(p.join(folder.path, p.basename(audio.file.path)));
    // The manifest already contains the complete metadata snapshot.
    try {
      final old = File('${audio.file.path}.json');
      if (await old.exists()) await old.delete();
    } on FileSystemException {/* An orphan sidecar does not hide audio. */}
    return TrashedAudio(folder, p.basename(moved.path),
        await _read(moved, _serialize(current)), deletedAt);
  }

  Future<List<TrashedAudio>> listTrash() async {
    if (!await trashRoot.exists()) return [];
    final rows = <TrashedAudio>[];
    await for (final folder in trashRoot.list()) {
      if (folder is! Directory) continue;
      try {
        final data = jsonDecode(
            await File(p.join(folder.path, 'record.json')).readAsString());
        if (data is! Map) continue;
        final name = data['originalFileName'];
        if (name is! String || !_fileName.hasMatch(name)) continue;
        final file = File(p.join(folder.path, name));
        if (!await file.exists()) continue;
        rows.add(TrashedAudio(
            folder,
            name,
            await _read(file, Map<String, dynamic>.from(data)),
            DateTime.tryParse(data['deletedAt']?.toString() ?? '') ??
                (await file.stat()).modified));
      } on FileSystemException {
        /* Retain damaged/incomplete entries for recovery. */
      } on FormatException {/* Retain data; do not auto-purge. */}
    }
    rows.sort((a, b) => b.deletedAt.compareTo(a.deletedAt));
    return rows;
  }

  Future<LocalAudio> restore(TrashedAudio item) async {
    if (!p.equals(p.normalize(item.directory.parent.absolute.path),
            p.normalize(trashRoot.absolute.path)) ||
        !_fileName.hasMatch(item.originalFileName)) {
      throw const FormatException('无效的回收站记录');
    }
    final target = File(p.join(root.path, item.originalFileName));
    if (await target.exists()) {
      throw const FormatException('本地已存在相同音频；现有文件和回收站副本均已保留');
    }
    await root.create(recursive: true);
    await _save(target, _serialize(item.audio));
    await item.audio.file.rename(target.path);
    await File(p.join(item.directory.path, 'record.json')).delete();
    try {
      await item.directory.delete();
    } on FileSystemException {/* Never remove unknown files. */}
    return _read(target);
  }
}
