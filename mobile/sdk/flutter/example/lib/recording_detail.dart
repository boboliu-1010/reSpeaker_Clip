import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:just_audio/just_audio.dart';
import 'companion_home.dart' show Note, ink, canvas, muted;
import 'model_api.dart';
import 'model_settings_page.dart';
import 'phone_recording.dart';

class RecordingDetail extends StatefulWidget {
  final Note note;
  final VoidCallback onChanged;
  const RecordingDetail(
      {super.key, required this.note, required this.onChanged});
  @override
  State<RecordingDetail> createState() => _RecordingDetailState();
}

class _RecordingDetailState extends State<RecordingDetail> {
  final player = AudioPlayer();
  ModelApi? api;
  bool ready = false, busy = false;
  String? error;
  int selected = 0;
  @override
  void initState() {
    super.initState();
    prepare();
  }

  Future<void> prepare() async {
    try {
      await player.setFilePath(await audioPath(widget.note.audioFile!));
      if (mounted) setState(() => ready = true);
    } catch (_) {
      if (mounted) setState(() => error = '音频无法播放，请检查文件是否完整。');
    }
  }

  @override
  void dispose() {
    api?.close();
    player.dispose();
    super.dispose();
  }

  Future<void> run(bool speech) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final settings = await ModelSettings.load();
      final config = speech ? settings.speech : settings.text;
      final endpoint =
          config.endpoint(speech ? 'audio/transcriptions' : 'chat/completions');
      if (!mounted) return;
      final confirmed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
                title: Text(speech ? '发送音频进行转写？' : '发送转写文本进行整理？'),
                content: Text(
                    '目标：${endpoint.origin}${endpoint.path}\n模型：${config.model}\n\n${speech ? '本条录音的完整音频' : '本条录音的转写文本'}将发送给此服务，可能产生费用。${speech ? '' : '结果为 AI 生成，需要核对；待办不会自动执行。'}已有结果会在成功后替换。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: const Text('确认发送'))
                ],
              ));
      if (confirmed != true || !mounted) return;
      api = ModelApi();
      if (speech) {
        final result = await api!
            .transcribe(config, await audioPath(widget.note.audioFile!));
        if (!mounted) return;
        widget.note.transcript = result;
        // A new transcript invalidates earlier derived results.
        widget.note.summary = '';
        widget.note.tasks = [];
        widget.note.completed.clear();
        selected = 0;
      } else {
        final result = await api!.process(config, widget.note.transcript);
        if (!mounted) return;
        widget.note.summary = result.summary;
        widget.note.tasks = result.tasks;
        widget.note.completed.clear();
        selected = 1;
      }
      widget.onChanged();
    } catch (e) {
      if (mounted) {
        setState(() =>
            error = e is ApiFailure ? e.message : '无法读取配置或处理内容，请检查模型设置后重试。');
      }
    } finally {
      api?.close();
      api = null;
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> rename() async {
    var value = widget.note.title;
    final result = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
                title: const Text('重命名录音'),
                content: TextFormField(
                    initialValue: value,
                    maxLength: 60,
                    onChanged: (s) => value = s),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () {
                        if (value.trim().isNotEmpty) {
                          Navigator.pop(ctx, value.trim());
                        }
                      },
                      child: const Text('保存'))
                ]));
    if (result != null && mounted) {
      setState(() => widget.note.title = result);
      widget.onChanged();
    }
  }

  Future<void> play() async {
    try {
      if (player.playing) {
        await player.pause();
      } else {
        if (player.processingState == ProcessingState.completed) {
          await player.seek(Duration.zero);
        }
        await player.play();
      }
    } catch (_) {
      if (mounted) setState(() => error = '播放失败，请检查音频输出设备。');
    }
  }

  @override
  Widget build(BuildContext context) {
    final note = widget.note;
    return PopScope(
        canPop: !busy,
        child: Scaffold(
            backgroundColor: canvas,
            appBar: AppBar(title: const Text('录音详情'), actions: [
              IconButton(
                  tooltip: '重命名',
                  onPressed: rename,
                  icon: const Icon(Icons.edit_outlined)),
              IconButton(
                  tooltip: '模型设置',
                  onPressed: busy
                      ? null
                      : () => Navigator.push(
                          context,
                          MaterialPageRoute<void>(
                              builder: (_) => const ModelSettingsPage())),
                  icon: const Icon(Icons.tune))
            ]),
            body: ListView(padding: const EdgeInsets.all(24), children: [
              const Text('手机麦克风 · 本地音频', style: TextStyle(color: muted)),
              const SizedBox(height: 12),
              Text(note.title,
                  style: const TextStyle(
                      fontSize: 28, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text('${note.date} · ${note.duration}'),
              const SizedBox(height: 24),
              Card(
                  color: ink,
                  child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(children: [
                        StreamBuilder<PlayerState>(
                            stream: player.playerStateStream,
                            builder: (_, snapshot) => Row(children: [
                                  IconButton(
                                      onPressed: ready ? play : null,
                                      icon: Icon(
                                          snapshot.data?.playing == true
                                              ? Icons.pause_circle
                                              : Icons.play_circle,
                                          size: 46,
                                          color: Colors.white)),
                                  const SizedBox(width: 12),
                                  Expanded(
                                      child: Text(ready ? '播放本地录音' : '正在准备音频…',
                                          style: const TextStyle(
                                              color: Colors.white)))
                                ])),
                        StreamBuilder<Duration>(
                            stream: player.positionStream,
                            builder: (_, snapshot) {
                              final total =
                                  (player.duration?.inMilliseconds ?? 0)
                                      .toDouble();
                              final position =
                                  (snapshot.data?.inMilliseconds ?? 0)
                                      .toDouble()
                                      .clamp(0.0, total > 0 ? total : 1.0);
                              return Slider(
                                  value: position,
                                  max: total > 0 ? total : 1,
                                  onChanged: ready
                                      ? (v) => player.seek(
                                          Duration(milliseconds: v.toInt()))
                                      : null);
                            }),
                      ]))),
              const SizedBox(height: 20),
              Wrap(spacing: 10, runSpacing: 10, children: [
                FilledButton.icon(
                    onPressed: busy ? null : () => run(true),
                    icon: const Icon(Icons.transcribe),
                    label: Text(note.transcript.isEmpty ? '识别语音' : '重新识别')),
                OutlinedButton.icon(
                    onPressed: busy || note.transcript.isEmpty
                        ? null
                        : () => run(false),
                    icon: const Icon(Icons.auto_awesome),
                    label: const Text('生成摘要与待办'))
              ]),
              if (busy) ...[
                const SizedBox(height: 20),
                const LinearProgressIndicator(),
                const SizedBox(height: 8),
                const Text('正在处理，请稍候。请保持应用在前台。'),
                TextButton(
                    onPressed: () {
                      api?.close();
                    },
                    child: const Text('取消请求（服务端可能继续处理）'))
              ],
              if (error != null)
                Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Text(error!,
                        style: const TextStyle(color: Colors.red))),
              const SizedBox(height: 24),
              SegmentedButton<int>(segments: const [
                ButtonSegment(value: 0, label: Text('转写')),
                ButtonSegment(value: 1, label: Text('摘要')),
                ButtonSegment(value: 2, label: Text('待办'))
              ], selected: {
                selected
              }, onSelectionChanged: (v) => setState(() => selected = v.first)),
              const SizedBox(height: 24),
              if (selected < 2) ...[
                SelectableText(
                    selected == 0
                        ? (note.transcript.isEmpty
                            ? '还没有转写。先在「我的 → 模型 API」配置语音识别服务，再点击「识别语音」。'
                            : note.transcript)
                        : (note.summary.isEmpty
                            ? '完成转写后，点击「生成摘要与待办」。'
                            : note.summary),
                    style: const TextStyle(fontSize: 16, height: 1.8)),
                if ((selected == 0 ? note.transcript : note.summary).isNotEmpty)
                  TextButton.icon(
                      onPressed: () async {
                        await Clipboard.setData(ClipboardData(
                            text: selected == 0
                                ? note.transcript
                                : note.summary));
                      },
                      icon: const Icon(Icons.copy),
                      label: const Text('复制文本')),
              ],
              if (selected == 2) ...[
                if (note.tasks.isEmpty) const Text('暂无待办。模型只提取原文中明确的行动事项。'),
                for (var i = 0; i < note.tasks.length; i++)
                  CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: note.completed.contains(i),
                      title: Text(note.tasks[i]),
                      onChanged: (v) {
                        setState(() {
                          if (v == true) {
                            note.completed.add(i);
                          } else {
                            note.completed.remove(i);
                          }
                        });
                        widget.onChanged();
                      }),
              ],
            ])));
  }
}
