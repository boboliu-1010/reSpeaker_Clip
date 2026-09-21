import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

class RecordedAudio {
  final String filename;
  final int seconds;
  const RecordedAudio(this.filename, this.seconds);
}

Future<String> audioPath(String filename) async =>
    '${(await getApplicationSupportDirectory()).path}/recordings/$filename';

class PhoneRecordingSheet extends StatefulWidget {
  const PhoneRecordingSheet({super.key});
  @override
  State<PhoneRecordingSheet> createState() => _PhoneRecordingSheetState();
}

class _PhoneRecordingSheetState extends State<PhoneRecordingSheet>
    with WidgetsBindingObserver {
  final recorder = AudioRecorder();
  final elapsed = Stopwatch();
  Timer? timer;
  StreamSubscription<RecordState>? subscription;
  bool active = false, paused = false, busy = true, saved = false;
  bool abandoned = false;
  String? error, filename;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    subscription = recorder.onStateChanged().listen((state) {
      if (!mounted || abandoned) return;
      if (state == RecordState.record) {
        elapsed.start();
      } else {
        elapsed.stop();
      }
      setState(() => paused = state != RecordState.record);
    });
    start();
  }

  Future<void> start() async {
    try {
      if (!await recorder.hasPermission()) {
        throw Exception('麦克风权限未开启，请在系统设置中允许 Clip Notes 使用麦克风。');
      }
      filename = '${DateTime.now().microsecondsSinceEpoch}.m4a';
      final path = await audioPath(filename!);
      await File(path).parent.create(recursive: true);
      if (!mounted) return;
      await recorder
          .start(
              const RecordConfig(
                  encoder: AudioEncoder.aacLc,
                  sampleRate: 16000,
                  numChannels: 1,
                  bitRate: 64000),
              path: path)
          .then((_) async {
        if (abandoned || !mounted) await recorder.cancel();
      }).timeout(const Duration(seconds: 15));
      active = true;
      elapsed.start();
      timer = Timer.periodic(const Duration(milliseconds: 300), (_) {
        if (mounted) setState(() {});
      });
    } on TimeoutException {
      abandoned = true;
      error = '音频设备响应超时。请退出录音并检查模拟器或系统麦克风输入，必要时重启应用。';
    } catch (e) {
      error = e.toString().contains('麦克风权限')
          ? '麦克风权限未开启，请在系统设置中允许录音。'
          : '无法启动麦克风，请检查输入设备及系统权限。';
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && active && !paused && !busy) {
      toggle();
    }
  }

  Future<void> toggle() async {
    setState(() => busy = true);
    try {
      if (paused) {
        await recorder.resume().timeout(const Duration(seconds: 10));
        elapsed.start();
      } else {
        await recorder.pause().timeout(const Duration(seconds: 10));
        elapsed.stop();
      }
    } catch (_) {
      error = '暂停或继续失败，请结束录音后重试。';
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> finish() async {
    setState(() => busy = true);
    try {
      final path = await recorder.stop().timeout(const Duration(seconds: 15));
      elapsed.stop();
      active = false;
      if (path == null ||
          !await File(path).exists() ||
          await File(path).length() == 0) {
        throw StateError('empty');
      }
      saved = true;
      if (mounted) {
        Navigator.pop(
            context, RecordedAudio(filename!, elapsed.elapsed.inSeconds));
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          error = '保存录音失败，请重试或放弃。';
          busy = false;
        });
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    subscription?.cancel();
    unawaited(cleanup());
    super.dispose();
  }

  Future<void> cleanup() async {
    try {
      if (!saved) {
        await recorder.cancel();
        if (filename != null) {
          final file = File(await audioPath(filename!));
          if (await file.exists()) await file.delete();
        }
      }
    } catch (_) {
      // Native audio services may already be unavailable during teardown.
    } finally {
      try {
        await recorder.dispose();
      } catch (_) {/* No active UI remains. */}
    }
  }

  @override
  Widget build(BuildContext context) {
    final seconds = elapsed.elapsed.inSeconds;
    return PopScope(
        canPop: !busy,
        child: SafeArea(
            child: Padding(
                padding: const EdgeInsets.all(28),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.mic_rounded, size: 42),
                  const SizedBox(height: 16),
                  Text(
                      active
                          ? (paused ? '录音已暂停' : '手机麦克风录音中')
                          : (error == null ? '准备录音' : '麦克风未就绪'),
                      style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 10),
                  const Text('音频保存在本机 · 离开应用自动暂停'),
                  const SizedBox(height: 24),
                  Text(
                      '${(seconds ~/ 60).toString().padLeft(2, '0')}:${(seconds % 60).toString().padLeft(2, '0')}',
                      style: const TextStyle(fontSize: 48)),
                  if (error != null)
                    Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text(error!,
                            style: const TextStyle(color: Colors.red))),
                  if (busy) const LinearProgressIndicator(),
                  const SizedBox(height: 24),
                  Row(children: [
                    OutlinedButton(
                        onPressed: active && !busy ? toggle : null,
                        child: Text(paused ? '继续' : '暂停')),
                    const SizedBox(width: 12),
                    Expanded(
                        child: FilledButton(
                            onPressed: active && !busy ? finish : null,
                            child: const Text('结束并保存')))
                  ]),
                  TextButton(
                      onPressed: busy ? null : () => Navigator.pop(context),
                      child: const Text('放弃录音')),
                ]))));
  }
}
