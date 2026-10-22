// Run from mobile/app with --packages=.dart_tool/package_config.json.
// Uses the unchanged desktop StorageClient. No token is printed or persisted.
import 'dart:convert';
import 'dart:io';

import 'package:respeaker_app/src/features/audio_storage/storage_client.dart';

double median(List<double> values) {
  final sorted = [...values]..sort();
  final middle = sorted.length ~/ 2;
  return sorted.length.isOdd
      ? sorted[middle]
      : (sorted[middle - 1] + sorted[middle]) / 2;
}

Future<void> main(List<String> args) async {
  if (args.length < 4 || args.length > 5) {
    stderr.writeln(
      'Usage: desktop_audio_http.dart <endpoint> <token-file> '
      '<audio-file> <output-directory> [rounds=3]',
    );
    exitCode = 64;
    return;
  }
  final rounds = args.length == 5 ? int.parse(args[4]) : 3;
  if (rounds < 1 || rounds > 5) throw ArgumentError('rounds must be 1..5');
  final source = File(args[2]);
  final bytes = await source.length();
  if (bytes <= 0) throw ArgumentError('Audio file must not be empty');
  final output = Directory(args[3]);
  await output.create(recursive: true);
  final run = await output.createTemp('desktop-http-');
  final sourceSha = await StorageClient.hash(source);
  final clientSource = File.fromUri(
    Platform.script.resolve(
      '../../mobile/app/lib/src/features/audio_storage/storage_client.dart',
    ),
  );
  final report = <String, dynamic>{
    'passed': false,
    'started_at_utc': DateTime.now().toUtc().toIso8601String(),
    'endpoint': args[0],
    'client': 'desktop StorageClient running on ${Platform.operatingSystem}',
    'client_source_sha256': await StorageClient.hash(clientSource),
    'scope': 'client API end-to-end, not GUI or pure wire throughput',
    'timing':
        'upload includes client hashes, requests and server completion; '
        'download includes transfer, local writes and client verification; '
        'post-test independent checksum is outside the timer',
    'fresh_cache_each_round': true,
    'rounds': rounds,
    'bytes_per_transfer': bytes,
    'source_sha256': sourceSha,
    'samples': <Map<String, dynamic>>[],
  };
  StorageClient? client;
  try {
    // Trust only in this process; never disable certificate/hostname validation.
    final certificate = Platform.environment['BOA_TEST_CA_FILE'];
    if (certificate != null && certificate.isNotEmpty) {
      SecurityContext.defaultContext.setTrustedCertificates(certificate);
      report['tls_trust'] = 'process-scoped certificate from BOA_TEST_CA_FILE';
    }
    final token = (await File(args[1]).readAsString()).trim();
    client = StorageClient(args[0], token);
    // Require authenticated HTTP access before any sample is recorded.
    await client.json('GET', '/api/audio/recordings?offset=0&limit=1');
    final ids = <String>{};
    final samples = report['samples'] as List<Map<String, dynamic>>;
    for (var index = 1; index <= rounds; index++) {
      final round = Directory('${run.path}/round-$index');
      final watch = Stopwatch()..start();
      final info = await client.upload(
        source,
        Directory('${round.path}/sessions'),
        filename:
            'desktop-http-${run.uri.pathSegments.where((s) => s.isNotEmpty).last}'
            '-r$index.${source.path.split('.').last}',
      );
      watch.stop();
      final uploadSeconds = watch.elapsedMicroseconds / 1000000;
      if (info['state'] != 'complete' ||
          info['sha256'] != sourceSha ||
          info['size'] != bytes ||
          !ids.add(info['id'] as String)) {
        throw StateError('Upload receipt or fresh-session verification failed');
      }
      final up = <String, dynamic>{
        'direction': 'upload',
        'round': index,
        'bytes': bytes,
        'seconds': uploadSeconds,
        'MB_per_second': bytes / 1000000 / uploadSeconds,
        'Mbps': bytes * 8 / 1000000 / uploadSeconds,
        'recording_id': info['id'],
        'complete_and_sha256_verified': true,
      };
      samples.add(up);
      stdout.writeln(jsonEncode(up));
      watch
        ..reset()
        ..start();
      final downloaded = await client.download(
        info,
        Directory('${round.path}/downloads'),
      );
      watch.stop();
      final downloadSeconds = watch.elapsedMicroseconds / 1000000;
      if (await downloaded.length() != bytes ||
          await StorageClient.hash(downloaded) != sourceSha) {
        throw StateError('Downloaded content mismatch');
      }
      final down = <String, dynamic>{
        'direction': 'download',
        'round': index,
        'bytes': bytes,
        'seconds': downloadSeconds,
        'MB_per_second': bytes / 1000000 / downloadSeconds,
        'Mbps': bytes * 8 / 1000000 / downloadSeconds,
        'recording_id': info['id'],
        'complete_and_sha256_verified': true,
      };
      samples.add(down);
      stdout.writeln(jsonEncode(down));
    }
    report['summary'] = {
      for (final direction in ['upload', 'download'])
        direction: {
          'median_MB_per_second': median(
            samples
                .where((s) => s['direction'] == direction)
                .map((s) => s['MB_per_second'] as double)
                .toList(),
          ),
          'median_Mbps': median(
            samples
                .where((s) => s['direction'] == direction)
                .map((s) => s['Mbps'] as double)
                .toList(),
          ),
        },
    };
    report['passed'] = true;
  } catch (error) {
    report['error'] = error.toString();
    stderr.writeln('Benchmark failed: $error');
    exitCode = 1;
  } finally {
    client?.close();
    report['finished_at_utc'] = DateTime.now().toUtc().toIso8601String();
    final path = '${run.path}/report.json';
    await File(path)
        .writeAsString(const JsonEncoder.withIndent('  ').convert(report));
    stdout.writeln('Report: $path');
  }
}
