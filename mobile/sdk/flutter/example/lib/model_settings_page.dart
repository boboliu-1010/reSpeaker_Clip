import 'package:flutter/material.dart';
import 'model_api.dart';

class ModelSettingsPage extends StatefulWidget {
  const ModelSettingsPage({super.key});
  @override
  State<ModelSettingsPage> createState() => _ModelSettingsPageState();
}

class _ModelSettingsPageState extends State<ModelSettingsPage> {
  final fields = List.generate(6, (_) => TextEditingController());
  bool loading = true, saving = false;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final config = await ModelSettings.load();
      if (!mounted) return;
      final values = [
        config.speech.baseUrl,
        config.speech.model,
        config.speech.key,
        config.text.baseUrl,
        config.text.model,
        config.text.key
      ];
      for (var i = 0; i < 6; i++) {
        fields[i].text = values[i];
      }
    } catch (_) {
      error = '无法读取安全存储，请重新打开后重试。';
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  void dispose() {
    for (final field in fields) {
      field.dispose();
    }
    super.dispose();
  }

  ModelConfig config(int offset) => ModelConfig(fields[offset].text.trim(),
      fields[offset + 1].text.trim(), fields[offset + 2].text.trim());
  Future<void> save() async {
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final speech = config(0), text = config(3);
      for (final value in [speech, text]) {
        if ([value.baseUrl, value.model, value.key].any((s) => s.isNotEmpty)) {
          value.endpoint('');
        }
      }
      await ModelSettings(speech, text).save();
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        setState(() => error = e is ApiFailure ? e.message : '安全存储写入失败，配置未保存。');
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Widget section(String title, int offset, String hint) => Card(
        margin: const EdgeInsets.only(bottom: 20),
        child: Padding(
            padding: const EdgeInsets.all(20),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(hint),
              const SizedBox(height: 14),
              for (var i = 0; i < 3; i++)
                Padding(
                    padding: const EdgeInsets.only(bottom: 14),
                    child: TextField(
                      controller: fields[offset + i],
                      obscureText: i == 2,
                      autocorrect: false,
                      enableSuggestions: false,
                      keyboardType:
                          i == 0 ? TextInputType.url : TextInputType.text,
                      decoration: InputDecoration(
                          labelText: ['API 基础地址', '模型名称', 'API Key（可选）'][i],
                          hintText:
                              i == 0 ? 'https://api.example.com/v1' : null,
                          border: const OutlineInputBorder()),
                    )),
            ])),
      );
  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('模型 API')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(24), children: [
              const Text(
                  '配置保存在本机安全存储。支持 OpenAI 兼容接口，仅在你确认后发送音频或文本。配置 API 不等于离线运行。',
                  style: TextStyle(height: 1.6)),
              const SizedBox(height: 12),
              const Text(
                  '填写包含 /v1 等前缀的基础地址，不要填写完整接口路径。目前要求 HTTPS；自建模型可通过 HTTPS 网关接入。'),
              const SizedBox(height: 24),
              section('语音识别', 0, 'POST /audio/transcriptions · multipart 音频文件'),
              section('摘要与待办', 3, 'POST /chat/completions · 文本消息'),
              if (error != null)
                Text(error!, style: const TextStyle(color: Colors.red)),
              FilledButton(
                  onPressed: saving ? null : save,
                  child: Text(saving ? '保存中…' : '安全保存')),
              TextButton(
                  onPressed: saving
                      ? null
                      : () async {
                          try {
                            await ModelSettings.clear();
                            if (mounted) {
                              for (final field in fields) {
                                field.clear();
                              }
                              setState(() {});
                            }
                          } catch (_) {
                            if (mounted) setState(() => error = '清除失败，请重试。');
                          }
                        },
                  child: const Text('清除本机 API 配置')),
            ]));
}
