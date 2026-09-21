import 'dart:async';
import 'phone_recording.dart';
import 'model_settings_page.dart';
import 'recording_detail.dart';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

const ink = Color(0xFF233D32);
const canvas = Color(0xFFF5F6F2);
const accent = Color(0xFFD2EAA8);
const muted = Color(0xFF7C847C);

class Note {
  String title;
  final String category;
  final String duration;
  final String date;
  String summary;
  String? audioFile;
  String transcript;
  List<String> tasks;
  Set<int> completed;
  bool get isDemo => audioFile == null;
  bool starred;
  Note(this.title, this.category, this.duration, this.date, this.summary,
      {this.starred = false,
      this.audioFile,
      this.transcript = '',
      List<String>? tasks,
      Set<int>? completed})
      : tasks = tasks ?? [],
        completed = completed ?? {};
  Map<String, dynamic> toJson() => {
        'title': title,
        'category': category,
        'duration': duration,
        'date': date,
        'summary': summary,
        'audioFile': audioFile,
        'transcript': transcript,
        'tasks': tasks,
        'completed': completed.toList(),
        'starred': starred
      };
  factory Note.fromJson(Map<String, dynamic> j) => Note(
      j['title'] as String,
      j['category'] as String,
      j['duration'] as String,
      j['date'] as String,
      j['summary'] as String,
      starred: j['starred'] == true,
      audioFile: j['audioFile'] as String?,
      transcript: j['transcript'] as String? ?? '',
      tasks: (j['tasks'] as List? ?? []).cast<String>(),
      completed: (j['completed'] as List? ?? []).cast<int>().toSet());
}

List<Note> sampleNotes() => [
      Note('产品设计周会', '会议', '24:18', '示例 · 今天 10:30',
          '先让录音变得简单，再让信息变得有用。第一版聚焦设备连接、录音管理与内容回顾。',
          starred: true),
      Note('散步时的灵感', '灵感', '03:42', '示例 · 今天 08:15',
          '给灵感一个随手可放的地方。用更少的操作，留下当时最重要的想法。'),
      Note('和设计师聊用户体验', '访谈', '38:06', '示例 · 昨天 16:20',
          '清晰的状态反馈比更多按钮更重要。同步过程应可理解、可取消、可恢复。'),
    ];

class CompanionHome extends StatefulWidget {
  final WidgetBuilder diagnosticsBuilder;
  const CompanionHome({super.key, required this.diagnosticsBuilder});
  @override
  State<CompanionHome> createState() => _CompanionHomeState();
}

class _CompanionHomeState extends State<CompanionHome> {
  int tab = 0;
  String query = '';
  final searchController = TextEditingController();
  String filter = '全部';
  List<Note> notes = sampleNotes();
  String server = '';
  bool busyRecording = false;
  @override
  void initState() {
    super.initState();
    unawaited(load());
  }

  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }

  Future<File> get store async => File(
      '${(await getApplicationSupportDirectory()).path}/clip_notes_preview_v1.json');
  Future<void> load() async {
    try {
      final f = await store;
      if (!await f.exists()) return;
      final data = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
      final restored = (data['notes'] as List)
          .map((e) => Note.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
      if (mounted) {
        setState(() {
          notes = restored;
          server = data['server'] as String? ?? '';
        });
      }
    } catch (_) {
      /* First preview or unavailable platform storage: keep samples. */
    }
  }

  Future<void> saveQueue = Future.value();
  Future<void> save() {
    final snapshot = jsonEncode(
        {'notes': notes.map((n) => n.toJson()).toList(), 'server': server});
    saveQueue = saveQueue.then((_) => writeSnapshot(snapshot));
    return saveQueue;
  }

  Future<void> writeSnapshot(String snapshot) async {
    try {
      final f = await store;
      await f.parent.create(recursive: true);
      final pending = File('${f.path}.tmp');
      await pending.writeAsString(snapshot, flush: true);
      await pending.rename(f.path);
    } catch (_) {
      if (mounted) message('本次修改暂存在内存中，本地写入未完成');
    }
  }

  void message(String text) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  Future<void> openNote(Note n) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => n.isDemo
            ? NoteDetail(
                note: n,
                onChanged: () {
                  setState(() {});
                  unawaited(save());
                })
            : RecordingDetail(
                note: n,
                onChanged: () {
                  setState(() {});
                  unawaited(save());
                })));
    if (mounted) setState(() {});
  }

  Future<void> record() async {
    if (busyRecording) return;
    busyRecording = true;
    final duration = await showModalBottomSheet<RecordedAudio>(
        context: context,
        isScrollControlled: true,
        backgroundColor: canvas,
        isDismissible: false,
        enableDrag: false,
        builder: (_) => const PhoneRecordingSheet());
    busyRecording = false;
    if (duration == null || !mounted) return;
    setState(() {
      filter = '全部';
      query = '';
      searchController.clear();
      tab = 0;
      notes.insert(
          0,
          Note(
              '手机录音 ${DateTime.now().hour.toString().padLeft(2, '0')}:${DateTime.now().minute.toString().padLeft(2, '0')}',
              '灵感',
              '${(duration.seconds ~/ 60).toString().padLeft(2, '0')}:${(duration.seconds % 60).toString().padLeft(2, '0')}',
              DateTime.now()
                  .toIso8601String()
                  .substring(0, 16)
                  .replaceAll('T', ' '),
              '',
              audioFile: duration.filename));
    });
    await save();
  }

  void tools() => Navigator.of(context)
      .push(MaterialPageRoute<void>(builder: widget.diagnosticsBuilder));
  Future<void> editServer() async {
    await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => const ModelSettingsPage()));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: canvas,
        body: SafeArea(
            bottom: false,
            child: IndexedStack(
                index: tab, children: [library(), device(), settings()])),
        bottomNavigationBar: Container(
            decoration: const BoxDecoration(
                color: Colors.white,
                border: Border(top: BorderSide(color: Color(0xFFE8EBE4)))),
            child: NavigationBar(
              selectedIndex: tab,
              onDestinationSelected: (v) => setState(() => tab = v),
              backgroundColor: Colors.white,
              elevation: 0,
              indicatorColor: accent,
              destinations: const [
                NavigationDestination(
                    icon: Icon(Icons.graphic_eq_rounded), label: '录音库'),
                NavigationDestination(
                    icon: Icon(Icons.sensors_rounded), label: '设备'),
                NavigationDestination(
                    icon: Icon(Icons.person_outline_rounded), label: '我的')
              ],
            )),
      );
  Widget heading(String eyebrow, String title, {Widget? trailing}) => Padding(
      padding: const EdgeInsets.fromLTRB(24, 18, 24, 22),
      child: Row(children: [
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(eyebrow,
              style: const TextStyle(
                  fontSize: 11,
                  letterSpacing: 2.2,
                  fontWeight: FontWeight.w700,
                  color: muted)),
          const SizedBox(height: 7),
          Text(title,
              style: const TextStyle(
                  fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -1))
        ])),
        if (trailing != null) trailing,
      ]));
  Widget library() {
    final visible = notes
        .where((n) =>
            (filter == '全部' ||
                (filter == '已收藏' ? n.starred : n.category == filter)) &&
            '${n.title} ${n.summary}'.contains(query))
        .toList();
    return CustomScrollView(slivers: [
      SliverToBoxAdapter(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        heading('CLIP NOTES', '让想法留下来',
            trailing: const CircleAvatar(
                backgroundColor: Colors.white,
                child: Icon(Icons.graphic_eq_rounded, color: ink))),
        Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                    color: ink, borderRadius: BorderRadius.circular(24)),
                child: Row(children: [
                  Expanded(
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                        const Tag('本地录音', color: accent, dark: true),
                        const SizedBox(height: 15),
                        const Text('每一段声音，\n都值得被记住。',
                            style: TextStyle(
                                color: Colors.white,
                                fontSize: 23,
                                fontWeight: FontWeight.w600,
                                height: 1.4)),
                        const SizedBox(height: 12),
                        const Text('手机麦克风 · 无需 Clip',
                            style: TextStyle(
                                color: Color(0xFFBACBBB), fontSize: 12)),
                        const SizedBox(height: 16),
                        SizedBox(
                            height: 39,
                            child: FilledButton.icon(
                                onPressed: record,
                                style: FilledButton.styleFrom(
                                    backgroundColor: accent,
                                    foregroundColor: ink),
                                icon: const Icon(Icons.add, size: 18),
                                label: const Text('手机录音')))
                      ])),
                  const SizedBox(width: 12),
                  const SizedBox(
                      width: 80,
                      height: 130,
                      child: CustomPaint(painter: ClipPainter())),
                ]))),
        Padding(
            padding: const EdgeInsets.fromLTRB(24, 23, 24, 12),
            child: TextField(
                controller: searchController,
                onChanged: (v) => setState(() => query = v),
                decoration: const InputDecoration(
                    hintText: '搜索录音、灵感或关键词',
                    prefixIcon: Icon(Icons.search_rounded, size: 22)))),
        SizedBox(
            height: 43,
            child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 24),
                children: ['全部', '会议', '灵感', '访谈', '已收藏']
                    .map((f) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                            labelStyle: TextStyle(
                                color: filter == f ? Colors.white : ink),
                            label: Text(f),
                            selected: filter == f,
                            showCheckmark: false,
                            onSelected: (_) => setState(() => filter = f))))
                    .toList())),
        Padding(
            padding: const EdgeInsets.fromLTRB(24, 22, 24, 13),
            child: Row(children: [
              const Text('最近录音',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const Spacer(),
              Text('${visible.length} 条记录',
                  style: const TextStyle(color: muted, fontSize: 12))
            ])),
      ])),
      if (visible.isEmpty)
        const SliverToBoxAdapter(
            child: Padding(
                padding: EdgeInsets.all(35),
                child: Center(
                    child: Text('没有找到匹配的录音', style: TextStyle(color: muted)))))
      else
        SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            sliver: SliverList.builder(
                itemCount: visible.length,
                itemBuilder: (_, i) => noteCard(visible[i], i))),
      const SliverToBoxAdapter(child: SizedBox(height: 22)),
    ]);
  }

  Widget noteCard(Note n, int i) => Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          child: InkWell(
              borderRadius: BorderRadius.circular(20),
              onTap: () => openNote(n),
              child: Padding(
                  padding: const EdgeInsets.all(17),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Container(
                              width: 43,
                              height: 43,
                              decoration: BoxDecoration(
                                  color: i.isEven
                                      ? const Color(0xFFEAF1DE)
                                      : const Color(0xFFFAEFE1),
                                  borderRadius: BorderRadius.circular(13)),
                              child: Icon(
                                  n.category == '会议'
                                      ? Icons.groups_outlined
                                      : n.category == '访谈'
                                          ? Icons.chat_bubble_outline
                                          : Icons.lightbulb_outline,
                                  color: ink,
                                  size: 22)),
                          const SizedBox(width: 12),
                          Expanded(
                              child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                Text(n.title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w700)),
                                const SizedBox(height: 5),
                                Text(n.date,
                                    style: const TextStyle(
                                        color: muted, fontSize: 11))
                              ])),
                          IconButton(
                              tooltip: n.starred ? '取消收藏' : '收藏',
                              onPressed: () {
                                setState(() => n.starred = !n.starred);
                                unawaited(save());
                              },
                              icon: Icon(
                                  n.starred
                                      ? Icons.bookmark_rounded
                                      : Icons.bookmark_border_rounded,
                                  size: 21,
                                  color: n.starred ? ink : muted))
                        ]),
                        const SizedBox(height: 15),
                        Row(children: [
                          Expanded(
                              child: SizedBox(
                                  height: 24,
                                  child: CustomPaint(
                                      painter:
                                          WavePainter(seed: n.title.length)))),
                          const SizedBox(width: 20),
                          Text(n.duration,
                              style: const TextStyle(
                                  fontSize: 12,
                                  color: muted,
                                  fontFeatures: [FontFeature.tabularFigures()]))
                        ]),
                        const SizedBox(height: 13),
                        Row(children: [
                          Tag(n.category),
                          const SizedBox(width: 8),
                          Text(
                              n.isDemo
                                  ? '示例转写与摘要'
                                  : (n.transcript.isEmpty
                                      ? '本地音频 · 待转写'
                                      : '已转写'),
                              style: TextStyle(color: muted, fontSize: 11)),
                          const Spacer(),
                          const Icon(Icons.arrow_forward_rounded,
                              size: 16, color: muted)
                        ]),
                      ])))));
  Widget device() =>
      ListView(padding: const EdgeInsets.only(bottom: 24), children: [
        heading('YOUR COMPANION', '设备'),
        Container(
            margin: const EdgeInsets.symmetric(horizontal: 24),
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
                color: ink, borderRadius: BorderRadius.circular(26)),
            child: Column(children: [
              const Tag('尚未连接', color: accent, dark: true),
              const SizedBox(height: 24),
              const SizedBox(
                  height: 180,
                  width: 110,
                  child: CustomPaint(painter: ClipPainter())),
              const SizedBox(height: 24),
              const Text('连接你的 Clip',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 25,
                      fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              const Text('随身记录，让灵感自然发生。',
                  style: TextStyle(color: Color(0xFFBACBBB))),
              const SizedBox(height: 24),
              SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                      onPressed: tools,
                      icon: const Icon(Icons.bluetooth_searching),
                      label: const Text('打开设备连接工具'),
                      style: FilledButton.styleFrom(
                          backgroundColor: accent, foregroundColor: ink)))
            ])),
        const Padding(
            padding: EdgeInsets.fromLTRB(27, 18, 27, 24),
            child: Text('模拟器可体验页面与演示流程。蓝牙配对、设备录音和 Wi-Fi 下载需要 iPhone 真机与 Clip。',
                style: TextStyle(color: muted, height: 1.6, fontSize: 13))),
        section('连接后可用', [
          setting(Icons.battery_5_bar_outlined, '电量与存储', '连接设备后读取', null),
          setting(Icons.sync_rounded, '录音同步', 'BLE / Wi-Fi · 尚未接入此界面', null),
          setting(
              Icons.system_update_alt_rounded, '固件升级', '请先完成真机录音与下载验证', null)
        ]),
      ]);
  Widget settings() =>
      ListView(padding: const EdgeInsets.only(bottom: 24), children: [
        heading('MAKE IT YOURS', '我的'),
        Container(
            margin: const EdgeInsets.symmetric(horizontal: 24),
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
                color: const Color(0xFFE8EFDC),
                borderRadius: BorderRadius.circular(22)),
            child: const Row(children: [
              CircleAvatar(
                  radius: 26,
                  backgroundColor: Colors.white,
                  child: Icon(Icons.person_outline, color: ink, size: 30)),
              SizedBox(width: 15),
              Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text('本地工作空间',
                        style: TextStyle(
                            fontSize: 18, fontWeight: FontWeight.w700)),
                    SizedBox(height: 6),
                    Text('不必登录，先留住想法',
                        style: TextStyle(color: muted, fontSize: 12))
                  ]))
            ])),
        const SizedBox(height: 25),
        section('数据与智能', [
          setting(
              Icons.dns_outlined, '模型 API', '语音识别与文本模型 · 本机安全存储', editServer),
          setting(
              Icons.auto_awesome_outlined, '转写与摘要', '在真实录音详情中发起处理', editServer),
          setting(Icons.shield_outlined, '本地优先', '录音与结果保存在本机，不自动上传',
              () => message('音频先保存在本机；每次调用 API 前会确认发送目标。待办只生成清单，不自动执行。'))
        ]),
        const SizedBox(height: 24),
        section('开发与帮助', [
          setting(Icons.tune_rounded, '设备调试工具', '官方 SDK 面板 · 真机验证', tools),
          setting(
              Icons.info_outline,
              '关于 Clip Notes',
              '本地录音与模型 API 0.2',
              () => showAboutDialog(
                      context: context,
                      applicationName: 'Clip Notes',
                      applicationVersion: '界面预览 0.1',
                      children: [
                        const Text(
                            '独立界面设计，设备功能参考 reSpeaker Clip。当前示例内容不代表真实录音或 AI 结果。')
                      ]))
        ]),
      ]);
  Widget section(String title, List<Widget> children) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title,
            style: const TextStyle(
                color: muted, fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(height: 10),
        Material(
            color: Colors.white,
            borderRadius: BorderRadius.circular(20),
            child: Column(children: children))
      ]));
  Widget setting(
          IconData icon, String title, String subtitle, VoidCallback? action) =>
      ListTile(
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 17, vertical: 5),
          leading: Icon(icon, color: ink, size: 23),
          title: Text(title,
              style:
                  const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          subtitle: Text(subtitle,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: muted, height: 1.5)),
          trailing: action == null
              ? null
              : const Icon(Icons.chevron_right, size: 18, color: muted),
          onTap: action);
}

class Tag extends StatelessWidget {
  final String text;
  final Color color;
  final bool dark;
  const Tag(this.text,
      {super.key, this.color = const Color(0xFFF0F3EB), this.dark = false});
  @override
  Widget build(BuildContext context) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration:
          BoxDecoration(color: color, borderRadius: BorderRadius.circular(7)),
      child: Text(text,
          style: TextStyle(
              fontSize: 10,
              color: dark ? ink : muted,
              fontWeight: FontWeight.w600)));
}

class WavePainter extends CustomPainter {
  final int seed;
  const WavePainter({this.seed = 3});
  @override
  void paint(Canvas c, Size s) {
    final p = Paint()
      ..color = const Color(0xFF9EAF8C)
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;
    final count = (s.width / 6).floor();
    for (var i = 0; i < count; i++) {
      final h = 3 +
          (math.sin(i * 1.7 + seed).abs() * .6 + math.sin(i * .32).abs() * .4) *
              (s.height - 4);
      c.drawLine(Offset(i * 6 + 2, (s.height - h) / 2),
          Offset(i * 6 + 2, (s.height + h) / 2), p);
    }
  }

  @override
  bool shouldRepaint(WavePainter old) => old.seed != seed;
}

class ClipPainter extends CustomPainter {
  const ClipPainter();
  @override
  void paint(Canvas c, Size s) {
    c.save();
    c.translate(s.width / 2, s.height / 2);
    c.rotate(.13);
    final w = s.width * .72, h = s.height * .88;
    final body = RRect.fromRectAndRadius(
        Rect.fromCenter(center: Offset.zero, width: w, height: h),
        const Radius.circular(20));
    c.drawShadow(Path()..addRRect(body), Colors.black, 12, true);
    c.drawRRect(
        body,
        Paint()
          ..shader = const LinearGradient(
                  colors: [Color(0xFFEBEDE4), Color(0xFFB8C1B2)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight)
              .createShader(body.outerRect));
    c.drawRRect(
        RRect.fromRectAndRadius(
            Rect.fromLTWH(-w / 2 + 9, -h / 2 + 13, w - 18, h * .23),
            const Radius.circular(9)),
        Paint()..color = ink);
    c.drawCircle(
        Offset(0, h * .14), 8, Paint()..color = const Color(0xFF6C8065));
    for (var i = -2; i <= 2; i++) {
      c.drawCircle(Offset(i * 5.0, h * .34), 1, Paint()..color = muted);
    }
    c.drawCircle(Offset(0, -h * .26), 2.5, Paint()..color = accent);
    c.restore();
  }

  @override
  bool shouldRepaint(ClipPainter old) => false;
}

class NoteDetail extends StatefulWidget {
  final Note note;
  final VoidCallback onChanged;
  const NoteDetail({super.key, required this.note, required this.onChanged});
  @override
  State<NoteDetail> createState() => _NoteDetailState();
}

class _NoteDetailState extends State<NoteDetail> {
  int selected = 0;
  final Set<int> completed = {};
  Future<void> rename() async {
    final controller = TextEditingController(text: widget.note.title);
    final title = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
                title: const Text('重命名录音'),
                content: TextField(
                    controller: controller, autofocus: true, maxLength: 60),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () {
                        if (controller.text.trim().isNotEmpty) {
                          Navigator.pop(ctx, controller.text.trim());
                        }
                      },
                      child: const Text('保存'))
                ]));
    if (title != null && mounted) {
      setState(() => widget.note.title = title);
      widget.onChanged();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      backgroundColor: canvas,
      appBar: AppBar(
          backgroundColor: canvas,
          title: const Text('录音详情', style: TextStyle(fontSize: 16)),
          actions: [
            IconButton(
                tooltip: '重命名',
                onPressed: rename,
                icon: const Icon(Icons.edit_outlined, size: 21)),
            IconButton(
                tooltip: '复制示例文本',
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(
                      text:
                          '${widget.note.title}\n[演示内容]\n${widget.note.summary}'));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context)
                        .showSnackBar(const SnackBar(content: Text('已复制示例文本')));
                  }
                },
                icon: const Icon(Icons.copy_outlined, size: 20))
          ]),
      body: ListView(padding: const EdgeInsets.all(24), children: [
        Row(children: [
          Tag(widget.note.category),
          const SizedBox(width: 8),
          const Tag('演示内容')
        ]),
        const SizedBox(height: 15),
        Text(widget.note.title,
            style: const TextStyle(
                fontSize: 29, fontWeight: FontWeight.w700, height: 1.3)),
        const SizedBox(height: 10),
        Text('${widget.note.date}  ·  ${widget.note.duration}',
            style: const TextStyle(color: muted, fontSize: 12)),
        const SizedBox(height: 24),
        Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
                color: ink, borderRadius: BorderRadius.circular(22)),
            child: Column(children: [
              const SizedBox(
                  height: 50,
                  width: double.infinity,
                  child: CustomPaint(painter: WavePainter(seed: 8))),
              const SizedBox(height: 16),
              Row(children: [
                const Icon(Icons.volume_off_outlined, color: accent),
                const SizedBox(width: 12),
                const Expanded(
                    child: Text('示例波形，无可播放音频',
                        style: TextStyle(color: Colors.white, fontSize: 12))),
                Text(widget.note.duration,
                    style: const TextStyle(color: accent, fontSize: 12))
              ])
            ])),
        const SizedBox(height: 27),
        SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('转写')),
              ButtonSegment(value: 1, label: Text('摘要')),
              ButtonSegment(value: 2, label: Text('待办'))
            ],
            selected: {
              selected
            },
            showSelectedIcon: false,
            onSelectionChanged: (v) => setState(() => selected = v.first)),
        const SizedBox(height: 24),
        if (selected == 0) ...[
          const Text('示例转写 · 非真实识别结果',
              style: TextStyle(color: muted, fontSize: 11)),
          const SizedBox(height: 18),
          transcript('00:00', '发言人 1', widget.note.summary),
          transcript('00:32', '发言人 2', '我们先把最重要的使用流程做好，保证录音能保存、能找到，也能方便地分享。'),
          transcript('01:05', '发言人 1', '接下来再连接真实设备，验证下载与音频播放。')
        ],
        if (selected == 1) ...[
          const Tag('示例摘要 · 未调用 AI'),
          const SizedBox(height: 20),
          const Text('核心结论',
              style: TextStyle(fontSize: 21, fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          Text(widget.note.summary,
              style: const TextStyle(height: 1.9, fontSize: 15)),
          const SizedBox(height: 24),
          const Text('值得记住',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          const Text('• 本地优先，录音由自己保管。\n• 先完成核心流程，再连接智能服务。\n• 给每一步操作清晰、可靠的反馈。',
              style: TextStyle(height: 2, color: muted))
        ],
        if (selected == 2) ...[
          const Text('示例待办 · 勾选状态仅在当前详情保留',
              style: TextStyle(color: muted, fontSize: 11)),
          const SizedBox(height: 12),
          ...['确认第一版页面与功能范围', '准备 Clip 和 iPhone 真机调试', '验证录音下载、播放与导出']
              .asMap()
              .entries
              .map((e) => CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(e.value,
                      style: TextStyle(
                          fontSize: 14,
                          decoration: completed.contains(e.key)
                              ? TextDecoration.lineThrough
                              : null)),
                  value: completed.contains(e.key),
                  onChanged: (v) => setState(() {
                        if (v == true) {
                          completed.add(e.key);
                        } else {
                          completed.remove(e.key);
                        }
                      })))
        ],
      ]));
  Widget transcript(String time, String speaker, String body) => Padding(
      padding: const EdgeInsets.only(bottom: 25),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(speaker,
              style:
                  const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          const SizedBox(width: 10),
          Text(time, style: const TextStyle(fontSize: 11, color: muted))
        ]),
        const SizedBox(height: 9),
        Text(body, style: const TextStyle(fontSize: 15, height: 1.8))
      ]));
}
