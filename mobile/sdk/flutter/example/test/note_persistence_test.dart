import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice_app/companion_home.dart';

void main() {
  test('Old preview records migrate without inventing audio', () {
    final note = Note.fromJson({
      'title': '旧记录',
      'category': '灵感',
      'duration': '00:10',
      'date': '今天',
      'summary': '示例'
    });
    expect(note.isDemo, true);
    expect(note.transcript, isEmpty);
  });
  test('Audio, transcription and checked tasks survive serialization', () {
    final note = Note('本地录音', '灵感', '00:10', '今天', '摘要',
        audioFile: '123.m4a', transcript: '转写', tasks: ['行动'], completed: {0});
    final restored = Note.fromJson(note.toJson());
    expect(restored.isDemo, false);
    expect(restored.audioFile, '123.m4a');
    expect(restored.transcript, '转写');
    expect(restored.completed, {0});
    expect(restored.tasks, ['行动']);
  });
}
