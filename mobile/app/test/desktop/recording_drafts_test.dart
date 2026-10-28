import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/local_library.dart';
import 'package:respeaker_app/src/features/desktop/recording_drafts.dart';

void main() {
  test(
      'unfinished recordings survive restart and are removed only after verified import',
      () async {
    final root = await Directory.systemTemp.createTemp('boa-drafts');
    addTearDown(() => root.delete(recursive: true));
    final dir = Directory('${root.path}/recordings');
    await dir.create();
    final draft = File('${dir.path}/record.wav');
    final bytes = List<int>.generate(100, (i) => i);
    await draft.writeAsBytes(bytes);
    await File('${dir.path}/empty.wav').writeAsBytes([1, 2]);
    final drafts = RecordingDrafts(dir);
    expect((await drafts.list()).map((f) => f.path), [draft.path]);
    expect(await draft.readAsBytes(), bytes);
    final audio = await RecordingDrafts(dir).save(
        draft, LocalLibrary(Directory('${root.path}/library')),
        name: '恢复录音');
    expect(audio.source, 'microphone');
    expect(await audio.file.readAsBytes(), bytes);
    expect(await draft.exists(), false);
    expect(await File('${dir.path}/empty.wav').exists(), true);
  });
  test('invalid name leaves staging recording intact', () async {
    final root = await Directory.systemTemp.createTemp('boa-draft-fail');
    addTearDown(() => root.delete(recursive: true));
    final draft = File('${root.path}/record.wav');
    await draft.writeAsBytes(List.filled(100, 0));
    await expectLater(
        RecordingDrafts(root).save(
            draft, LocalLibrary(Directory('${root.path}/library')),
            name: '../bad'),
        throwsFormatException);
    expect(await draft.length(), 100);
  });
}
