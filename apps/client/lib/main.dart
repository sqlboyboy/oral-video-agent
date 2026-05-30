import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(const OralVideoAgentApp());
}

class OralVideoAgentApp extends StatelessWidget {
  const OralVideoAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '智能口播智能体',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF725CFF)),
        useMaterial3: true,
      ),
      home: const WorkbenchPage(),
    );
  }
}

class WorkbenchPage extends StatefulWidget {
  const WorkbenchPage({super.key});

  @override
  State<WorkbenchPage> createState() => _WorkbenchPageState();
}

class _WorkbenchPageState extends State<WorkbenchPage> {
  static const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://127.0.0.1:8000');

  final urlController = TextEditingController();
  final productController = TextEditingController();
  final audienceController = TextEditingController();
  final scriptController = TextEditingController();

  Map<String, dynamic>? task;
  Map<String, dynamic>? providers;
  Map<String, dynamic>? output;
  List<Map<String, dynamic>> taskSummaries = const [];
  bool loading = false;
  String message = '';
  String selectedStyle = '同款口播';
  String selectedVoice = 'default-female';
  String selectedBgm = 'default-light';
  double bgmVolume = 0.18;
  double subtitleSize = 42;

  @override
  void initState() {
    super.initState();
    loadProviders();
    loadTaskSummaries();
  }

  Future<void> loadProviders() async {
    try {
      final res = await http.get(Uri.parse('$apiBase/api/providers'));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('${res.statusCode}: ${res.body}');
      }
      setState(() => providers = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>);
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> loadTaskSummaries() async {
    try {
      final res = await http.get(Uri.parse('$apiBase/api/tasks'));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('${res.statusCode}: ${res.body}');
      }
      final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => taskSummaries = (body['items'] as List).cast<Map<String, dynamic>>());
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> callApi(Future<http.Response> Function() action) async {
    setState(() {
      loading = true;
      message = '';
    });
    try {
      final res = await action();
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('${res.statusCode}: ${res.body}');
      }
      setState(() => task = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>);
      await loadTaskSummaries();
      scriptController.text = (task?['rewritten_script'] as String?)?.isNotEmpty == true
          ? task!['rewritten_script'] as String
          : task?['original_script'] as String? ?? '';
    } catch (e) {
      setState(() => message = e.toString());
    } finally {
      setState(() => loading = false);
    }
  }

  Future<void> createTask() async {
    await callApi(() => http.post(
          Uri.parse('$apiBase/api/tasks'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'douyin_url': urlController.text.trim()}),
        ));
  }

  Future<void> rewrite() async {
    final taskId = task?['task_id'];
    if (taskId == null) return;
    await callApi(() => http.post(
          Uri.parse('$apiBase/api/tasks/$taskId/rewrite'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'style': selectedStyle,
            'product_info': productController.text.trim(),
            'target_audience': audienceController.text.trim(),
          }),
        ));
  }

  Future<void> deleteTask(String taskId) async {
    try {
      final res = await http.delete(Uri.parse('$apiBase/api/tasks/$taskId'));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('${res.statusCode}: ${res.body}');
      }
      if (task?['task_id'] == taskId) {
        setState(() {
          task = null;
          output = null;
          scriptController.clear();
        });
      }
      await loadTaskSummaries();
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> loadOutput() async {
    final taskId = task?['task_id'];
    if (taskId == null) return;
    try {
      final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId/output'));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('${res.statusCode}: ${res.body}');
      }
      setState(() => output = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>);
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> render() async {
    final taskId = task?['task_id'];
    if (taskId == null) return;
    await callApi(() => http.post(
          Uri.parse('$apiBase/api/tasks/$taskId/render'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'script': scriptController.text.trim(),
            'voice_id': selectedVoice,
            'bgm_id': selectedBgm,
            'bgm_volume': bgmVolume,
            'subtitle_style': {
              'font_size': subtitleSize.round(),
              'color': '#FFFFFF',
              'outline_color': '#000000',
              'position': 'bottom',
              'max_chars_per_line': 18,
            }
          }),
        ));
    await loadOutput();
  }

  @override
  Widget build(BuildContext context) {
    final status = task?['status'] ?? '未创建';
    final rewriteProvider = providers?['rewrite_provider'] ?? '未知';
    final anthropicModel = providers?['anthropic_model'];
    final outputReady = output?['ready'] == true;
    final outputSize = output?['size_bytes'] ?? 0;
    final progressSteps = (task?['progress_steps'] as List?)?.cast<Map<String, dynamic>>() ?? const <Map<String, dynamic>>[];
    return Scaffold(
      appBar: AppBar(title: const Text('智能口播智能体')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text('复制抖音链接，一键解析、仿写、配音、BGM、字幕并生成视频', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Card(
                child: ListTile(
                  title: const Text('当前 AI Provider'),
                  subtitle: Text('文案仿写：$rewriteProvider${anthropicModel == null ? '' : ' · $anthropicModel'}'),
                  trailing: IconButton(onPressed: loadProviders, icon: const Icon(Icons.refresh)),
                ),
              ),
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      const Expanded(child: Text('历史任务')),
                      TextButton(onPressed: loadTaskSummaries, child: const Text('刷新')),
                    ]),
                    if (taskSummaries.isEmpty) const Text('暂无历史任务'),
                    ...taskSummaries.take(5).map((item) => ListTile(
                          dense: true,
                          title: Text(item['title'] ?? item['task_id']),
                          subtitle: Text('状态：${item['status']} · 成品：${item['output_ready'] == true ? '已生成' : '未生成'}'),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline),
                            onPressed: () => deleteTask(item['task_id'] as String),
                          ),
                          onTap: () async {
                            final res = await http.get(Uri.parse('$apiBase/api/tasks/${item['task_id']}'));
                            if (res.statusCode >= 200 && res.statusCode < 300) {
                              setState(() => task = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>);
                              scriptController.text = (task?['rewritten_script'] as String?)?.isNotEmpty == true
                                  ? task!['rewritten_script'] as String
                                  : task?['original_script'] as String? ?? '';
                              await loadOutput();
                            }
                          },
                        )),
                  ]),
                ),
              ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('1. 导入视频'),
                    const SizedBox(height: 8),
                    TextField(controller: urlController, decoration: const InputDecoration(labelText: '抖音链接', border: OutlineInputBorder())),
                    const SizedBox(height: 8),
                    FilledButton(onPressed: loading ? null : createTask, child: const Text('创建并解析')),
                  ]),
                ),
              ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('2. 文案仿写 · 状态：$status'),
                    const SizedBox(height: 8),
                    Text('原文：${task?['original_script'] ?? '-'}'),
                    if (progressSteps.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: progressSteps.map((step) {
                          final done = step['status'] == 'completed';
                          final running = step['status'] == 'running';
                          return Chip(
                            avatar: Icon(done ? Icons.check_circle : running ? Icons.pending : Icons.radio_button_unchecked, size: 18),
                            label: Text('${step['label']} · ${step['status']}'),
                          );
                        }).toList(),
                      ),
                    ],
                    const SizedBox(height: 8),
                    Wrap(spacing: 12, runSpacing: 12, children: [
                      DropdownButton<String>(value: selectedStyle, items: const [
                        DropdownMenuItem(value: '同款口播', child: Text('同款口播')),
                        DropdownMenuItem(value: '带货', child: Text('带货')),
                        DropdownMenuItem(value: '知识口播', child: Text('知识口播')),
                        DropdownMenuItem(value: '种草', child: Text('种草')),
                      ], onChanged: (v) => setState(() => selectedStyle = v ?? selectedStyle)),
                      SizedBox(width: 220, child: TextField(controller: productController, decoration: const InputDecoration(labelText: '产品/服务信息'))),
                      SizedBox(width: 180, child: TextField(controller: audienceController, decoration: const InputDecoration(labelText: '目标人群'))),
                      FilledButton.tonal(onPressed: task == null || loading ? null : rewrite, child: const Text('一键仿写')),
                    ]),
                    const SizedBox(height: 8),
                    TextField(controller: scriptController, minLines: 5, maxLines: 10, decoration: const InputDecoration(labelText: '可编辑文案', border: OutlineInputBorder())),
                  ]),
                ),
              ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('3. 声音 / BGM / 字幕'),
                    Wrap(spacing: 16, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      DropdownButton<String>(value: selectedVoice, items: const [
                        DropdownMenuItem(value: 'default-female', child: Text('清澈女声')),
                        DropdownMenuItem(value: 'default-male', child: Text('沉稳男声')),
                        DropdownMenuItem(value: 'energetic', child: Text('活力主播')),
                      ], onChanged: (v) => setState(() => selectedVoice = v ?? selectedVoice)),
                      DropdownButton<String>(value: selectedBgm, items: const [
                        DropdownMenuItem(value: 'default-light', child: Text('轻快日常')),
                        DropdownMenuItem(value: 'default-tech', child: Text('科技律动')),
                        DropdownMenuItem(value: 'default-warm', child: Text('温暖叙事')),
                      ], onChanged: (v) => setState(() => selectedBgm = v ?? selectedBgm)),
                      SizedBox(width: 220, child: Slider(value: bgmVolume, min: 0, max: 1, label: 'BGM ${(bgmVolume * 100).round()}%', onChanged: (v) => setState(() => bgmVolume = v))),
                      SizedBox(width: 220, child: Slider(value: subtitleSize, min: 16, max: 96, label: '字幕 ${subtitleSize.round()}', onChanged: (v) => setState(() => subtitleSize = v))),
                    ]),
                    const SizedBox(height: 8),
                    FilledButton(onPressed: task == null || loading ? null : render, child: const Text('合成视频')),
                  ]),
                ),
              ),
              if (task?['task_id'] != null)
                Card(
                  child: ListTile(
                    title: Text(outputReady ? '成品已生成' : '成品未就绪'),
                    subtitle: SelectableText(outputReady ? '大小：$outputSize bytes\n路径：${output?['path']}' : '点击刷新检查合成结果'),
                    trailing: IconButton(onPressed: loadOutput, icon: const Icon(Icons.refresh)),
                  ),
                ),
              if (message.isNotEmpty) Text(message, style: const TextStyle(color: Colors.red)),
              if (loading) const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator()),
            ],
          ),
        ),
      ),
    );
  }
}
