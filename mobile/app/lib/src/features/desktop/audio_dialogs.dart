import 'package:flutter/material.dart';
import 'package:ffmpeg_kit_flutter_new/ffprobe_kit.dart';
import 'local_library.dart';

String audioSource(String source) => switch (source) {
      'microphone' => 'Mac 麦克风',
      'import' => '导入文件',
      'download' => '服务器下载',
      _ => '历史文件（来源未知）',
    };

Future<String?> askAudioName(BuildContext context,
    {required String title,
    required String initial,
    required String extension,
    String? hint}) async {
  final controller = TextEditingController(text: initial);
  String? error;
  final result = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(builder: (context, update) {
            void save() {
              try {
                Navigator.pop(
                    context, audioDisplayName(controller.text, extension));
              } on FormatException catch (e) {
                update(() => error = e.message);
              }
            }

            return AlertDialog(
                title: Text(title),
                content: SizedBox(
                    width: 420,
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      if (hint != null) ...[
                        Text(hint),
                        const SizedBox(height: 16)
                      ],
                      TextField(
                          controller: controller,
                          autofocus: true,
                          onSubmitted: (_) => save(),
                          decoration: InputDecoration(
                              labelText: '音频名称',
                              suffixText: '.$extension',
                              errorText: error)),
                    ])),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('取消')),
                  FilledButton(onPressed: save, child: const Text('保存'))
                ]);
          }));
  // Let the closing route finish using its controller before disposal.
  Future.delayed(const Duration(milliseconds: 350), controller.dispose);
  return result;
}

Future<int?> probeDuration(LocalAudio audio) async {
  if (audio.durationMs != null) return audio.durationMs;
  try {
    final session = await FFprobeKit.getMediaInformation(audio.file.path);
    final seconds =
        double.tryParse(session.getMediaInformation()?.getDuration() ?? '');
    return seconds != null && seconds.isFinite && seconds >= 0
        ? (seconds * 1000).round()
        : null;
  } catch (_) {
    return null;
  }
}

Future<void> showAudioDetails(BuildContext context, LocalAudio audio,
        {required String presence}) =>
    showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('音频详情'),
                content: SizedBox(
                    width: 460,
                    child: FutureBuilder<int?>(
                        future: probeDuration(audio),
                        builder: (context, snapshot) => Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  SelectableText(audio.name,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleMedium),
                                  const SizedBox(height: 20),
                                  Text('保存位置　$presence'),
                                  Text('来源　${audioSource(audio.source)}'),
                                  Text('格式　${audio.extension.toUpperCase()}'),
                                  Text(
                                      '大小　${audio.bytes} 字节（${(audio.bytes / 1048576).toStringAsFixed(2)} MB）'),
                                  Text(
                                      '时长　${snapshot.connectionState != ConnectionState.done ? '读取中…' : snapshot.data == null ? '未知（无法解析）' : '${(snapshot.data! / 1000).toStringAsFixed(1)} 秒'}'),
                                  Text(
                                      '入库时间　${audio.addedAt.toLocal().toString().split('.').first}'),
                                  const SizedBox(height: 16),
                                  const Text('改名仅影响本地显示；服务器已上传文件保留原名称。',
                                      style:
                                          TextStyle(color: Color(0xff667085))),
                                ]))),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('关闭'))
                ]));
