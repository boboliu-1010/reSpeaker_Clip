import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/desktop/clip_status.dart';

void main() {
  test('firmware replies preserve zero and false, with seconds and MB units',
      () {
    final status = ClipStatus.fromReplies(
      {'ok': true, 'firmware': 'roger-1.2'},
      {
        'ok': true,
        'data': {
          'state': 'PAUSED',
          'recording': false,
          'battery': 0,
          'charging': false,
          'duration': 65,
          'free_space': 512
        }
      },
    );
    expect(status.firmware, 'roger-1.2');
    expect(status.state, '已暂停');
    expect(status.battery, 0);
    expect(status.charging, false);
    expect(status.durationSeconds, 65);
    expect(status.freeMB, 512);
  });
  test('failed or incomplete replies never invent idle or device values', () {
    final status = ClipStatus.fromReplies({
      'ok': false,
      'firmware': 'bad'
    }, {
      'ok': false,
      'data': {'battery': 90, 'state': 'IDLE'}
    });
    expect(status.firmware, isNull);
    expect(status.battery, isNull);
    expect(status.state, '未知');
    expect(status.freeMB, isNull);
    expect(
        ClipStatus.fromReplies({}, {
          'ok': true,
          'data': {'recording': true}
        }).state,
        '录音中');
  });
}
