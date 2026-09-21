import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sensecraft_voice_app/model_api.dart';

void main() {
  test('Speech upload is multipart and parses Unicode text', () async {
    final dir = await Directory.systemTemp.createTemp('clip-api-test');
    addTearDown(() => dir.delete(recursive: true));
    final file =
        await File('${dir.path}/synthetic.m4a').writeAsBytes([1, 2, 3]);
    final api = ModelApi(MockClient((request) async {
      expect(request.url.path, '/v1/audio/transcriptions');
      expect(request.followRedirects, false);
      expect(request.headers['content-type'], contains('multipart/form-data'));
      final body = utf8.decode(request.bodyBytes);
      expect(body, contains('name="model"'));
      expect(body, contains('speech-model'));
      expect(body, contains('filename="recording.m4a"'));
      return http.Response.bytes(utf8.encode('{"text":"测试转写"}'), 200);
    }));
    expect(
        await api.transcribe(
            const ModelConfig('https://example.com/v1', 'speech-model', ''),
            file.path),
        '测试转写');
  });

  test('Reject insecure and ambiguous endpoints', () {
    for (final url in [
      'http://example.com/v1',
      'https://user:pass@host/v1',
      'https://host/v1?key=x'
    ]) {
      expect(
          () =>
              ModelConfig(url, 'model', 'secret').endpoint('chat/completions'),
          throwsA(isA<ApiFailure>()));
    }
  });
  test('Text task sends configured model and returns structured result',
      () async {
    final client = MockClient((request) async {
      expect(request.url.toString(), 'https://example.com/v1/chat/completions');
      expect(request.headers['Authorization'], 'Bearer secret');
      expect(request.followRedirects, false);
      expect(jsonDecode(request.body)['model'], 'my-model');
      return http.Response(
          jsonEncode({
            'choices': [
              {
                'message': {'content': '{"summary":"结论","tasks":["行动"]}'}
              }
            ]
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    });
    final result = await ModelApi(client).process(
        ModelConfig('https://example.com/v1/', 'my-model', 'secret'), '原文');
    expect(result.summary, '结论');
    expect(result.tasks, ['行动']);
  });
  test('Provider errors never expose body or credentials', () async {
    final api = ModelApi(
        MockClient((_) async => http.Response('secret audio contents', 401)));
    await expectLater(
        api.process(
            ModelConfig('https://example.com/v1', 'm', 'secret'), 'private'),
        throwsA(isA<ApiFailure>().having((e) => e.message, 'safe message',
            '服务返回 HTTP 401，请检查地址、模型、密钥或额度。')));
  });
}
