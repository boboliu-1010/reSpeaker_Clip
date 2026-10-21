import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/backup_queue.dart';
import 'package:respeaker_app/src/features/desktop/local_library.dart';

void main() {
  test('automatic off runs only explicit manual jobs, including after restart',
      () async {
    final dir = await Directory.systemTemp.createTemp('backup-policy-');
    addTearDown(() => dir.delete(recursive: true));
    final q = BackupQueue(File('${dir.path}/jobs.json'));
    final a = LocalAudio(File('${dir.path}/a.wav'), 'a.wav', 1);
    final b = LocalAudio(File('${dir.path}/b.wav'), 'b.wav', 1);
    await q.enqueue(a, 'http://localhost:1');
    await q.enqueue(b, 'http://localhost:1');
    await q.requestManual(b, 'http://localhost:1');
    final restored = BackupQueue(q.file);
    await restored.load();
    final sent = <String>[];
    await restored.drain((audio, url) async {
      sent.add(audio.name);
    }, automaticAllowed: () => false, endpoint: 'http://localhost:1');
    expect(sent, ['b.wav']);
    expect(restored.status(a, 'http://localhost:1'), '待备份');
    expect(restored.status(b, 'http://localhost:1'), '已备份');
    await restored.drain((audio, url) async {
      sent.add(audio.name);
    }, automaticAllowed: () => true, endpoint: 'http://localhost:1');
    expect(sent, ['b.wav', 'a.wav']);
  });

  test(
      'per-file retry preserves unrelated failures and reports safe progress/errors',
      () async {
    final dir = await Directory.systemTemp.createTemp('backup-policy-');
    addTearDown(() => dir.delete(recursive: true));
    final q = BackupQueue(File('${dir.path}/jobs.json'));
    final a = LocalAudio(File('${dir.path}/a.wav'), 'a.wav', 1);
    final b = LocalAudio(File('${dir.path}/b.wav'), 'b.wav', 1);
    await q.enqueue(a, 'http://localhost:1');
    await q.enqueue(b, 'http://localhost:1');
    await q.drain((audio, url) async {
      throw const SocketException('private-value');
    });
    await q.requestManual(a, 'http://localhost:1');
    final unrelated = q.jobs().firstWhere((j) => j.audio.name == 'b.wav');
    expect(unrelated.attempts, 1);
    expect(unrelated.state, 'failed');
    expect(unrelated.error, isNot(contains('private-value')));
    await q.drain((audio, url) async {
      expect(audio.name, 'a.wav');
      q.setProgress(audio, url, .5);
      expect(q.jobs().firstWhere((j) => j.audio.name == 'a.wav').progress, .5);
      await expectLater(q.removeFile(audio), throwsStateError);
    }, automaticAllowed: () => false);
    expect(q.status(a, 'http://localhost:1'), '已备份');
    await q.removeFile(a);
    expect(q.jobs().length, 1);
    expect(q.jobs().single.audio.name, 'b.wav');
  });
  test(
      'automatic reconciliation does not inherit completed manual authorization',
      () async {
    final dir = await Directory.systemTemp.createTemp('backup-reconcile');
    addTearDown(() => dir.delete(recursive: true));
    final q = BackupQueue(File('${dir.path}/jobs.json'));
    final audio = LocalAudio(File('${dir.path}/a.wav'), 'a.wav', 1);
    await q.requestManual(audio, 'http://localhost:1');
    var sends = 0;
    await q.drain((a, e) async {
      sends++;
    }, automaticAllowed: () => false);
    await q.enqueue(audio, 'http://localhost:1', resetComplete: true);
    await q.drain((a, e) async {
      sends++;
    }, automaticAllowed: () => false);
    expect(sends, 1);
    expect(q.jobs().single.state, 'pending');
    expect(q.jobs().single.manual, false);
  });
}
