import 'package:flutter_test/flutter_test.dart';
import 'package:sensecraft_voice/src/at/at_command_redaction.dart';

void main() {
  test('BLE configuration credentials never enter diagnostic text', () {
    expect(redactAtCommand('AT+NETCFG=home,secret-password'),
        'AT+NETCFG=<redacted>');
    expect(redactAtCommand('AT+UPLOADCFG=host,9528,clip,secret-token'),
        'AT+UPLOADCFG=<redacted>');
    expect(redactAtCommand('AT+GSTAT'), 'AT+GSTAT');
  });
}
