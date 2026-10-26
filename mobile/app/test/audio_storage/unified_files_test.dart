import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:respeaker_app/src/features/audio_storage/storage_client.dart';

void main() {
  test(
      'unified list includes Clip source and falls back only on missing endpoint',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    var unified = true;
    final paths = <String>[];
    server.listen((r) {
      paths.add(r.uri.path);
      r.response.headers.contentType = ContentType.json;
      if (r.uri.path == '/api/boa/v1/audio-files') {
        if (!unified) {
          r.response.statusCode = 404;
          r.response.write('{}');
        } else {
          r.response.write(jsonEncode({
            'items': [
              {'id': '1', 'source': 'clip_direct'}
            ]
          }));
        }
      } else {
        r.response.write('{"items":[]}');
      }
      r.response.close();
    });
    final client = StorageClient('http://127.0.0.1:${server.port}', 'test');
    try {
      expect((await client.list()).single['source'], 'clip_direct');
      unified = false;
      expect(await client.list(), isEmpty);
      expect(paths.last, '/api/audio/recordings');
    } finally {
      client.close();
      await server.close(force: true);
    }
  });
  test('upload cache identity includes the account credential', () {
    final a = StorageClient('http://localhost:8765', 'alice');
    final b = StorageClient('http://localhost:8765', 'bob');
    expect(a.accountKey, isNot(b.accountKey));
    a.close();
    b.close();
  });
}
