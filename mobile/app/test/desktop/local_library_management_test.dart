import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/local_library.dart';

void main() {
  late Directory temp;
  late LocalLibrary library;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('boa-management-');
    library = LocalLibrary(Directory('${temp.path}/data/library'));
  });
  tearDown(() => temp.delete(recursive: true));

  test('rename/export/trash/restart/restore preserve bytes, source and time',
      () async {
    final source = File('${temp.path}/source.wav');
    await source.writeAsBytes([1, 2, 3, 4]);
    final audio = await library.importFile(source,
        source: 'microphone', durationMs: 1500);
    final renamed = await library.rename(audio, '项目会议');
    expect(renamed.name, '项目会议.wav');
    expect(renamed.file.path, audio.file.path);
    expect(renamed.addedAt, audio.addedAt);
    expect(renamed.source, 'microphone');
    final export = File('${temp.path}/export.wav');
    await library.export(renamed, export);
    expect(await export.readAsBytes(), [1, 2, 3, 4]);
    await library.moveToTrash(renamed);
    expect(await library.list(), isEmpty);
    final reopened = LocalLibrary(library.root);
    final trash = await reopened.listTrash();
    expect(trash.single.audio.name, '项目会议.wav');
    final restored = await reopened.restore(trash.single);
    expect(await restored.file.readAsBytes(), [1, 2, 3, 4]);
    expect(restored.addedAt, audio.addedAt);
    expect(restored.durationMs, 1500);
    expect(restored.source, 'microphone');
    expect(await reopened.listTrash(), isEmpty);
    expect(await source.exists(), isTrue);
  });

  test('invalid rename and export onto itself leave audio intact', () async {
    final source = File('${temp.path}/source.wav');
    await source.writeAsBytes([9, 8]);
    final audio = await library.importFile(source);
    for (final name in ['', '../escape', 'a/b', 'a\\b', 'bad\nname']) {
      await expectLater(library.rename(audio, name), throwsFormatException);
    }
    await expectLater(library.export(audio, audio.file), throwsFormatException);
    expect(await audio.file.readAsBytes(), [9, 8]);
  });

  test('duplicate restore preserves both copies instead of overwriting',
      () async {
    final source = File('${temp.path}/source.wav');
    await source.writeAsBytes([7, 7]);
    final audio = await library.importFile(source);
    await library.moveToTrash(audio);
    await library.importFile(source);
    final deleted = (await library.listTrash()).single;
    await expectLater(library.restore(deleted), throwsFormatException);
    expect((await library.list()).length, 1);
    expect((await library.listTrash()).length, 1);
  });
  test(
      'export refuses other library audio and symlink aliases without modifying bytes',
      () async {
    final a = File('${temp.path}/a.wav');
    final b = File('${temp.path}/b.wav');
    await a.writeAsBytes([1, 2]);
    await b.writeAsBytes([8, 9]);
    final first = await library.importFile(a);
    final second = await library.importFile(b);
    final alias = Link('${temp.path}/alias');
    await alias.create(library.root.path);
    for (final destination in [
      second.file,
      File('${alias.path}/${second.file.uri.pathSegments.last}')
    ]) {
      await expectLater(
          library.export(first, destination), throwsFormatException);
      expect(await second.file.readAsBytes(), [8, 9]);
      expect(await first.file.readAsBytes(), [1, 2]);
    }
  });
}
