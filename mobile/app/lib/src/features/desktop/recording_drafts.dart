import 'dart:io';
import 'local_library.dart';

/// Staging files are never discarded on cancel, failed import, or restart.
class RecordingDrafts {
  final Directory directory;
  RecordingDrafts(this.directory);
  Future<List<File>> list() async {
    if (!await directory.exists()) return [];
    final result = <File>[];
    await for (final entry in directory.list()) {
      if (entry is File &&
          entry.path.endsWith('.wav') &&
          await entry.length() > 44) {
        result.add(entry);
      }
    }
    result.sort((a, b) => b.path.compareTo(a.path));
    return result;
  }

  Future<LocalAudio> save(File draft, LocalLibrary library,
      {required String name, int? durationMs}) async {
    if (draft.parent.path != directory.path || await draft.length() <= 44) {
      throw const FormatException('暂存录音无效；文件已保留');
    }
    final audio = await library.importFile(draft,
        name: audioDisplayName(name, 'wav'),
        source: 'microphone',
        durationMs: durationMs);
    await draft.delete();
    return audio;
  }
}
