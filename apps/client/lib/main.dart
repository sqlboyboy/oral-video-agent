import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  runApp(const OralVideoAgentApp());
}

class OralVideoAgentApp extends StatelessWidget {
  const OralVideoAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '杰速口播智能体',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6B6DFF),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF11131B),
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
  static const apiBase =
      String.fromEnvironment('API_BASE', defaultValue: 'http://127.0.0.1:8000');
  static const cyan = Color(0xFF2F9BFF);
  static const pink = Color(0xFFE260D4);
  static const panelBg = Color(0xFF1D2030);
  static const panelBg2 = Color(0xFF24283A);
  static const purpleLine = Color(0xFF7E54E8);

  final urlController = TextEditingController();
  final productController = TextEditingController();
  final audienceController = TextEditingController();
  final originalScriptController = TextEditingController();
  final rewrittenScriptController = TextEditingController();
  final publisherNicknameController = TextEditingController();
  final publishTitleController = TextEditingController();
  final publishBodyController = TextEditingController();
  final publishTopicsController = TextEditingController();

  Map<String, dynamic>? task;
  Map<String, dynamic>? providers;
  Map<String, dynamic>? output;
  Map<String, dynamic>? mouthAtlasDiagnosis;
  List<Map<String, dynamic>> rewriteStyles = const [];
  List<Map<String, dynamic>> voices = const [];
  List<Map<String, dynamic>> digitalHumans = const [];
  List<Map<String, dynamic>> bgmTracks = const [];
  List<Map<String, dynamic>> publisherAccounts = const [];
  List<Map<String, dynamic>> publishJobs = const [];
  bool loading = false;
  bool renderingVideo = false;
  bool diagnosingMouthAtlas = false;
  bool publishing = false;
  bool generatingPublishContent = false;
  String message = '';
  bool messageIsError = false;
  String publishContentGeneratedKey = '';
  String selectedStyle = '同款口播';
  String selectedWordCount = '300字';
  String selectedVoice = 'classic-female';
  String selectedBgm = 'default-light';
  String selectedDigitalHuman = '';
  String selectedDigitalHumanEngine = 'heygem-local';
  String selectedPublishPlatform = 'douyin';
  String selectedPublisherAccount = '';
  String selectedPublishMode = 'direct';
  String selectedMediaSubTab = 'subtitles';
  bool toothHd = true;
  bool randomMotion = false;
  bool mouthApertureEnabled = true;
  double speechRate = 1.0;
  double bgmVolume = 0.18;
  double subtitleSize = 18;
  double mouthApertureStrength = 0.50;
  double mouthApertureEnergyThreshold = 0.24;
  double mouthApertureMinRatio = 0.07;
  double mouthApertureMaxRatio = 0.36;
  double mouthApertureAttack = 1.0;
  double mouthApertureRelease = 1.0;
  int outputRefresh = 0;
  Timer? renderPollTimer;
  Player? _voicePlayer;
  bool _isPlayingVoice = false;

  @override
  void initState() {
    super.initState();
    loadBootstrap();
    loadPublisherAccounts();
  }

  @override
  void dispose() {
    renderPollTimer?.cancel();
    _voicePlayer?.dispose();
    urlController.dispose();
    productController.dispose();
    audienceController.dispose();
    originalScriptController.dispose();
    rewrittenScriptController.dispose();
    publisherNicknameController.dispose();
    publishTitleController.dispose();
    publishBodyController.dispose();
    publishTopicsController.dispose();
    super.dispose();
  }

  Future<void> loadBootstrap() async {
    try {
      final res = await http.get(Uri.parse('$apiBase/api/bootstrap'));
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final loadedVoices =
          (body['voices'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
      final loadedHumans =
          (body['digital_humans'] as List?)?.cast<Map<String, dynamic>>() ??
              const [];
      final loadedBgm =
          (body['bgm'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
      setState(() {
        final loadedProviders = body['providers'] as Map<String, dynamic>?;
        providers = loadedProviders;
        rewriteStyles =
            (body['rewrite_styles'] as List?)?.cast<Map<String, dynamic>>() ??
                const [];
        voices = loadedVoices;
        digitalHumans = loadedHumans;
        bgmTracks = loadedBgm;
        mouthApertureEnabled =
            loadedProviders?['wav2lip_aperture_atlas_enabled'] == true;
        mouthApertureStrength = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_atlas_strength',
          fallback: mouthApertureEnabled ? 0.50 : mouthApertureStrength,
          zeroFallback: 0.50,
        );
        mouthApertureEnergyThreshold = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_energy_threshold',
          fallback: mouthApertureEnergyThreshold,
        );
        mouthApertureMinRatio = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_min_ratio',
          fallback: mouthApertureMinRatio,
        );
        mouthApertureMaxRatio = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_max_ratio',
          fallback: mouthApertureMaxRatio,
        );
        mouthApertureAttack = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_attack',
          fallback: mouthApertureAttack,
        );
        mouthApertureRelease = _providerDoubleFrom(
          loadedProviders,
          'wav2lip_aperture_release',
          fallback: mouthApertureRelease,
        );
        final voiceIds = loadedVoices.map((v) => v['voice_id']).toSet();
        if (!voiceIds.contains(selectedVoice) && loadedVoices.isNotEmpty) {
          selectedVoice = loadedVoices.first['voice_id'] as String;
        }
        if (selectedDigitalHuman.isEmpty && loadedHumans.isNotEmpty) {
          selectedDigitalHuman =
              loadedHumans.first['digital_human_id'] as String;
        }
        final bgmIds = loadedBgm.map((v) => v['bgm_id']).toSet();
        if (!bgmIds.contains(selectedBgm) && loadedBgm.isNotEmpty) {
          selectedBgm = loadedBgm.first['bgm_id'] as String;
        }
        if (rewriteStyles.isNotEmpty &&
            !rewriteStyles.any((s) => s['name'] == selectedStyle)) {
          selectedStyle = rewriteStyles.first['name'] as String;
        }
      });
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> loadPublisherAccounts() async {
    try {
      final accountsRes =
          await http.get(Uri.parse('$apiBase/api/publisher/accounts'));
      _check(accountsRes);
      final accountsBody = jsonDecode(utf8.decode(accountsRes.bodyBytes))
          as Map<String, dynamic>;
      final jobsRes = await http.get(Uri.parse('$apiBase/api/publish-jobs'));
      _check(jobsRes);
      final jobsBody =
          jsonDecode(utf8.decode(jobsRes.bodyBytes)) as Map<String, dynamic>;
      final accounts =
          (accountsBody['items'] as List?)?.cast<Map<String, dynamic>>() ??
              const [];
      final visibleAccounts = _dedupePublisherAccounts(accounts);
      final jobs = (jobsBody['items'] as List?)?.cast<Map<String, dynamic>>() ??
          const [];
      setState(() {
        publisherAccounts = visibleAccounts;
        publishJobs = jobs.reversed.take(6).toList();
        final selectedStillValid = visibleAccounts.any((account) {
          return account['account_id'] == selectedPublisherAccount &&
              account['platform'] == selectedPublishPlatform;
        });
        if (!selectedStillValid) {
          selectedPublisherAccount = _firstPublisherAccountForPlatform(
              visibleAccounts, selectedPublishPlatform);
        }
        _syncPublisherNicknameField(visibleAccounts);
      });
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  void _syncPublisherNicknameField(List<Map<String, dynamic>> accounts) {
    Map<String, dynamic>? selected;
    for (final account in accounts) {
      if (account['account_id'] == selectedPublisherAccount) {
        selected = account;
        break;
      }
    }
    final nickname = (selected?['nickname'] as String? ?? '').trim();
    if (nickname.isNotEmpty) {
      publisherNicknameController.text = nickname;
    } else {
      publisherNicknameController.text = '登录后自动识别';
    }
  }

  List<Map<String, dynamic>> _dedupePublisherAccounts(
    List<Map<String, dynamic>> accounts,
  ) {
    final kept = <Map<String, dynamic>>[];
    final pendingPlatforms = <String>{};
    for (final account in accounts.reversed) {
      final nickname = (account['nickname'] as String? ?? '').trim();
      final status = account['status'] as String? ?? '';
      final platform = account['platform'] as String? ?? '';
      final isPendingPlaceholder = nickname.isEmpty && status != 'logged_in';
      if (isPendingPlaceholder && !pendingPlatforms.add(platform)) {
        continue;
      }
      kept.add(account);
    }
    return kept.reversed.toList(growable: false);
  }

  String _firstPublisherAccountForPlatform(
    List<Map<String, dynamic>> accounts,
    String platform,
  ) {
    for (final account in accounts) {
      if (account['platform'] == platform) {
        return account['account_id'] as String;
      }
    }
    return '';
  }

  void _selectPublisherPlatform(String platform) {
    selectedPublishPlatform = platform;
    selectedPublisherAccount =
        _firstPublisherAccountForPlatform(publisherAccounts, platform);
    _syncPublisherNicknameField(publisherAccounts);
  }

  void showInfo(String text) {
    setState(() {
      message = text;
      messageIsError = false;
    });
  }

  void showError(String text) {
    setState(() {
      message = text;
      messageIsError = true;
    });
  }

  Future<void> createPublisherAccount() async {
    final nickname = publisherNicknameController.text.trim();
    if (nickname.isNotEmpty && nickname != '登录后自动识别') {
      final existing = publisherAccounts.where((account) {
        return account['platform'] == selectedPublishPlatform &&
            ((account['nickname'] as String? ?? '').trim() == nickname);
      }).toList();
      if (existing.isNotEmpty) {
        setState(() =>
            selectedPublisherAccount = existing.first['account_id'] as String);
        showInfo('该账号已存在，已为你选中。');
        return;
      }
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/publisher/accounts'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'platform': selectedPublishPlatform,
          'nickname': nickname == '登录后自动识别' ? '' : nickname,
        }),
      );
      _check(res);
      final account =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      await loadPublisherAccounts();
      setState(() {
        selectedPublisherAccount = account['account_id'] as String;
        message = '账号已添加，请点击“登录”打开平台登录窗口，登录成功后会自动识别账号名称。';
        messageIsError = false;
      });
    });
  }

  Future<void> loginPublisherAccount() async {
    if (selectedPublisherAccount.isEmpty) {
      showError('请先添加或选择发布账号。');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse(
            '$apiBase/api/publisher/accounts/$selectedPublisherAccount/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'timeout_seconds': 900}),
      );
      _check(res);
      await loadPublisherAccounts();
      showInfo('已请求打开登录窗口，请按平台提示完成扫码或验证。');
    });
  }

  Future<void> checkPublisherSession() async {
    if (selectedPublisherAccount.isEmpty) return;
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse(
            '$apiBase/api/publisher/accounts/$selectedPublisherAccount/check-session'),
      );
      _check(res);
      await loadPublisherAccounts();
    });
  }

  Future<void> createPublishJobs() async {
    final taskId = _taskId;
    if (taskId == null) {
      showError('请先创建视频任务。');
      return;
    }
    if (selectedPublisherAccount.isEmpty) {
      showError('请先选择发布账号。');
      return;
    }
    if (publishTitleController.text.trim().isEmpty ||
        publishBodyController.text.trim().isEmpty ||
        publishTopicsController.text.trim().isEmpty) {
      await generatePublishContent(silent: true);
    }
    final publishTitle = _limitPublishTitle(publishTitleController.text);
    if (publishTitle != publishTitleController.text.trim()) {
      publishTitleController.text = publishTitle;
    }
    final topics = publishTopicsController.text
        .split(RegExp(r'[\s,#，]+'))
        .map((value) => value.trim())
        .where((value) => value.isNotEmpty)
        .toList();
    setState(() => publishing = true);
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/publish-jobs'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'account_ids': [selectedPublisherAccount],
          'title': publishTitle,
          'body': publishBodyController.text.trim(),
          'topics': topics,
          'publish_mode': selectedPublishMode,
        }),
      );
      _check(res);
      await loadPublisherAccounts();
      await _loadTask(taskId);
      showInfo('发布任务已创建，请在下方查看任务状态。');
    });
    setState(() => publishing = false);
  }

  Future<void> generatePublishContent({bool silent = false}) async {
    final taskId = _taskId;
    if (taskId == null || generatingPublishContent) return;
    setState(() {
      generatingPublishContent = true;
      if (!silent) {
        message = '正在生成发布标题、正文和话题';
        messageIsError = false;
      }
    });
    try {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/publish-content'),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final topics =
          (body['topics'] as List?)?.map((item) => item.toString()).toList() ??
              const <String>[];
      setState(() {
        publishTitleController.text =
            _limitPublishTitle(body['title'] as String? ?? '');
        publishBodyController.text = body['body'] as String? ?? '';
        publishTopicsController.text = topics
            .map((topic) => '#${topic.replaceFirst(RegExp(r'^#+'), '')}')
            .join(' ');
        if (!silent) {
          message = '发布内容已生成';
          messageIsError = false;
        }
      });
    } catch (e) {
      if (!silent) showError(e.toString());
    } finally {
      if (mounted) setState(() => generatingPublishContent = false);
    }
  }

  String _limitPublishTitle(String value) {
    return String.fromCharCodes(value.trim().runes.take(20));
  }

  void _check(http.Response res) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('${res.statusCode}: ${utf8.decode(res.bodyBytes)}');
    }
  }

  Future<void> _loadTask(String taskId) async {
    final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId'));
    _check(res);
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    setState(() => task = body);
    _syncEditors(body);
  }

  void _syncEditors(Map<String, dynamic> currentTask) {
    originalScriptController.text =
        currentTask['original_script'] as String? ?? '';
    rewrittenScriptController.text =
        currentTask['rewritten_script'] as String? ?? '';
    final taskId = currentTask['task_id'] as String? ?? '';
    final publishSource = ((currentTask['rewritten_script'] as String?) ??
            (currentTask['original_script'] as String?) ??
            '')
        .trim();
    final generationKey = '$taskId:${publishSource.hashCode}';
    if (taskId.isNotEmpty &&
        publishSource.isNotEmpty &&
        publishContentGeneratedKey != generationKey) {
      publishContentGeneratedKey = generationKey;
      Future.microtask(() => generatePublishContent(silent: true));
    }
  }

  Future<void> createTask() async {
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'douyin_url': urlController.text.trim()}),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        task = body;
        output = null;
        outputRefresh++;
        publishContentGeneratedKey = '';
        publishTitleController.clear();
        publishBodyController.clear();
        publishTopicsController.clear();
      });
      _syncEditors(body);
      final taskId = body['task_id'] as String;
      await _pollImport(taskId);
    });
  }

  Future<void> uploadSourceVideo() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4', 'mov', 'mkv', 'webm'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    await _runBusy(() async {
      final request =
          http.MultipartRequest('POST', Uri.parse('$apiBase/api/tasks/upload'));
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        task = body;
        output = null;
        outputRefresh++;
        publishContentGeneratedKey = '';
        publishTitleController.clear();
        publishBodyController.clear();
        publishTopicsController.clear();
      });
      _syncEditors(body);
    });
  }

  Future<void> _pollImport(String taskId) async {
    final deadline = DateTime.now().add(const Duration(minutes: 3));
    while (DateTime.now().isBefore(deadline)) {
      await Future.delayed(const Duration(seconds: 3));
      final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId'));
      if (res.statusCode < 200 || res.statusCode >= 300) return;
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => task = body);
      _syncEditors(body);
      final status = body['status'] as String? ?? '';
      if (status == 'failed') {
        setState(() => message = body['error_message'] as String? ?? '导入失败');
        return;
      }
      if ((body['original_script'] as String? ?? '').isNotEmpty ||
          status == 'transcribed' ||
          status == 'completed') {
        return;
      }
    }
  }

  Future<void> rewrite() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final source = originalScriptController.text.trim();
    if (source.isEmpty) {
      setState(() => message = '请先提取或填写原始文案');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/rewrite'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'style': selectedStyle,
          'source_script': source,
          'product_info': productController.text.trim(),
          'target_audience': audienceController.text.trim(),
        }),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => task = body);
      _syncEditors(body);
    });
  }

  Future<void> generateTitle() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    await _runBusy(() async {
      final res =
          await http.post(Uri.parse('$apiBase/api/tasks/$taskId/title'));
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => task = body);
    });
  }

  Future<void> cloneVoice() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final script = _renderScript;
    if (script.isEmpty) {
      setState(() => message = '请先生成或填写文案');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/voice'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(_renderPayload(script)),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => task = body);
    });
  }

  Future<void> playVoice() async {
    final taskId = _taskId;
    if (taskId == null) {
      setState(() => message = '请先选择任务');
      return;
    }
    final voiceUrl = '$apiBase/api/tasks/$taskId/voice';
    try {
      if (_voicePlayer != null) {
        await _voicePlayer?.stop();
        _voicePlayer?.dispose();
        _voicePlayer = null;
      }
      if (_isPlayingVoice) {
        setState(() => _isPlayingVoice = false);
        return;
      }
      _voicePlayer = Player();
      setState(() => _isPlayingVoice = true);
      await _voicePlayer!.open(Media(voiceUrl));
      await _voicePlayer!.play();
      _voicePlayer!.stream.completed.listen((_) {
        if (mounted) setState(() => _isPlayingVoice = false);
      });
    } catch (e) {
      setState(() {
        message = '播放失败: ${e.toString()}';
        _isPlayingVoice = false;
      });
      _voicePlayer?.dispose();
      _voicePlayer = null;
    }
  }

  Future<void> uploadDigitalHuman() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4', 'mov', 'mkv', 'webm'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    await _runBusy(() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase/api/digital-humans/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final item = body['digital_human'] as Map<String, dynamic>;
      await loadBootstrap();
      final digitalHumanId = item['digital_human_id'] as String;
      setState(() => selectedDigitalHuman = digitalHumanId);
    });
  }

  Future<void> loadMouthAtlasDiagnosis(String digitalHumanId) async {
    if (digitalHumanId.isEmpty) {
      setState(() => mouthAtlasDiagnosis = null);
      return;
    }
    setState(() => diagnosingMouthAtlas = true);
    try {
      final uri = Uri.parse('$apiBase/api/digital-humans/atlas-diagnosis')
          .replace(queryParameters: {'digital_human_id': digitalHumanId});
      final res = await http.get(uri);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      if (!mounted || selectedDigitalHuman != digitalHumanId) return;
      setState(() => mouthAtlasDiagnosis = body);
    } catch (e) {
      if (!mounted || selectedDigitalHuman != digitalHumanId) return;
      setState(() {
        mouthAtlasDiagnosis = {
          'verdict': 'diagnosis_failed',
          'warnings': [e.toString()],
        };
      });
    } finally {
      if (mounted && selectedDigitalHuman == digitalHumanId) {
        setState(() => diagnosingMouthAtlas = false);
      }
    }
  }

  void selectDigitalHuman(String value) {
    setState(() {
      selectedDigitalHuman = value;
      mouthAtlasDiagnosis = null;
    });
  }

  Future<void> uploadVoice() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['wav', 'mp3', 'm4a', 'aac'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    await _runBusy(() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase/api/voices/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final item = body['voice'] as Map<String, dynamic>;
      await loadBootstrap();
      setState(() => selectedVoice = item['voice_id'] as String);
    });
  }

  Future<void> uploadBgm() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['wav', 'mp3', 'm4a', 'aac', 'flac'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    await _runBusy(() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase/api/bgm/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final item = body['bgm'] as Map<String, dynamic>;
      await loadBootstrap();
      setState(() => selectedBgm = item['bgm_id'] as String);
    });
  }

  Future<void> render() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final script = _renderScript;
    if (script.isEmpty) {
      setState(() => message = '请先生成或填写文案');
      return;
    }
    setState(() {
      loading = true;
      renderingVideo = true;
      message = '正在生成视频，可以点击停止生成中断任务';
    });
    _startRenderPolling(taskId);
    try {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/render'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(_renderPayload(script)),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() => task = body);
      _syncEditors(body);
      final errorMessage = body['error_message'] as String?;
      if ((body['status'] as String?) == 'failed' &&
          errorMessage != null &&
          errorMessage.isNotEmpty) {
        setState(() => message = errorMessage);
        return;
      }
      await loadOutput();
    } catch (e) {
      setState(() => message = e.toString());
    } finally {
      _stopRenderPolling();
      setState(() {
        loading = false;
        renderingVideo = false;
      });
    }
  }

  void _startRenderPolling(String taskId) {
    renderPollTimer?.cancel();
    renderPollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId'));
        if (res.statusCode < 200 || res.statusCode >= 300) return;
        final body =
            jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
        if (!mounted) return;
        setState(() {
          task = body;
          message = _renderingMessage(body);
        });
        final status = body['status'] as String? ?? '';
        if (status == 'completed' || status == 'failed') {
          _stopRenderPolling();
        }
      } catch (_) {
        // Keep the long-running render request alive; the main request will
        // surface the final error if polling temporarily fails.
      }
    });
  }

  void _stopRenderPolling() {
    renderPollTimer?.cancel();
    renderPollTimer = null;
  }

  String _renderingMessage(Map<String, dynamic> currentTask) {
    final status = currentTask['status'] as String? ?? '';
    if (status == 'failed') {
      return currentTask['error_message'] as String? ?? '生成未完成，系统已记录状态，请稍后重试';
    }
    final active = _activeProgressStep(currentTask);
    if (active != null) {
      return '正在处理：${active['label']}';
    }
    return '正在生成视频，可以点击停止生成中断任务';
  }

  Future<void> stopRender() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    try {
      final res = await http
          .post(Uri.parse('$apiBase/api/tasks/$taskId/cancel-render'));
      _check(res);
      await _loadTask(taskId);
      setState(() {
        message = '已停止生成';
        loading = false;
        renderingVideo = false;
      });
    } catch (e) {
      setState(() => message = e.toString());
    }
  }

  Future<void> loadOutput() async {
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId/output'));
    _check(res);
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    setState(() {
      output = body;
      outputRefresh++;
      if (body['ready'] == true) {
        message = '视频已生成，可以预览';
      } else if ((body['detail'] as String? ?? '').isNotEmpty) {
        message = body['detail'] as String;
      }
    });
  }

  Future<void> previewOutputVideo() async {
    await loadOutput();
    final url = _outputVideoUrl;
    if (url == null) {
      setState(() => message = '请先生成视频，生成完成后再预览');
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _VideoPlayerDialog(url: url),
    );
  }

  Future<void> openOutputVideo() async {
    final taskId = _taskId;
    if (taskId == null) {
      setState(() => message = '请先创建视频任务');
      return;
    }
    if (_outputVideoPath == null) {
      await loadOutput();
    }
    final path = _outputVideoPath;
    if (path == null || path.isEmpty) {
      setState(() => message = '还没有可打开的成品视频');
      return;
    }
    try {
      if (Platform.isWindows) {
        await Process.start('explorer.exe', ['/select,', path]);
      } else if (Platform.isMacOS) {
        await Process.start('open', ['-R', path]);
      } else {
        await Process.start('xdg-open', [File(path).parent.path]);
      }
    } catch (e) {
      setState(() => message = '打开视频失败：$e');
    }
  }

  Future<void> _runBusy(Future<void> Function() action) async {
    setState(() {
      loading = true;
      message = '';
      messageIsError = false;
    });
    try {
      await action();
    } catch (e) {
      showError(e.toString());
    } finally {
      if (mounted && !renderingVideo) {
        setState(() => loading = false);
      }
    }
  }

  String get _renderScript {
    final rewritten = rewrittenScriptController.text.trim();
    if (rewritten.isNotEmpty) return rewritten;
    return originalScriptController.text.trim();
  }

  Map<String, dynamic> _renderPayload(String script) {
    return {
      'script': script,
      'voice_id': selectedVoice,
      'digital_human_engine': selectedDigitalHumanEngine,
      'digital_human_id': selectedDigitalHuman.startsWith('custom:') ||
              selectedDigitalHuman.startsWith('template:')
          ? selectedDigitalHuman
          : null,
      'motion_mode': randomMotion ? 'random' : 'loop',
      'expression_mode': toothHd ? 'sync' : 'basic',
      'bgm_id': selectedBgm,
      'bgm_volume': bgmVolume,
      'subtitle_style': {
        'font_size': subtitleSize.round(),
        'color': '#FFFFFF',
        'outline_color': '#000000',
        'position': 'bottom',
        'max_chars_per_line': 18,
      },
    };
  }

  String? get _taskId => task?['task_id'] as String?;

  String? get _sourceVideoUrl {
    final taskId = _taskId;
    if (taskId == null || task?['source_video'] == null) return null;
    return '$apiBase/api/tasks/$taskId/source';
  }

  String? get _outputVideoUrl {
    final taskId = _taskId;
    if (taskId == null) return null;
    final hasOutputPath = (output?['ready'] == true) ||
        ((task?['output_video_path'] as String? ?? '').isNotEmpty);
    if (!hasOutputPath) return null;
    return '$apiBase/api/tasks/$taskId/download?v=$outputRefresh';
  }

  String? get _outputVideoPath {
    final outputPath = output?['path'] as String?;
    if (outputPath != null && outputPath.isNotEmpty) return outputPath;
    final taskPath = task?['output_video_path'] as String?;
    if (taskPath != null && taskPath.isNotEmpty) return taskPath;
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final status = task?['status'] as String? ?? '未开始';
    final steps =
        (task?['progress_steps'] as List?)?.cast<Map<String, dynamic>>() ??
            const [];
    return Scaffold(
      body: Column(
        children: [
          _banner(),
          _tabStrip(),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  flex: 3,
                  child: _leftPanel(status, steps),
                ),
                const VerticalDivider(width: 1, color: Color(0xFF31364A)),
                Expanded(
                  flex: 4,
                  child: _centerPanel(),
                ),
                const VerticalDivider(width: 1, color: Color(0xFF31364A)),
                Expanded(
                  flex: 3,
                  child: _rightPanel(),
                ),
              ],
            ),
          ),
          if (message.isNotEmpty) _messageBar(),
        ],
      ),
    );
  }

  Widget _banner() {
    return Container(
      height: 86,
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          colors: [Color(0xFF151725), Color(0xFF211C3D), Color(0xFF151725)],
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.menu, color: Colors.white70),
          const SizedBox(width: 18),
          const Icon(Icons.auto_awesome, color: Color(0xFFA86CFF), size: 28),
          const SizedBox(width: 8),
          const Text(
            '杰速口播智能体',
            style: TextStyle(fontSize: 21, fontWeight: FontWeight.w900),
          ),
          const Spacer(),
          _topPill('手动', true),
          const SizedBox(width: 8),
          _topPill('自动', false),
          const SizedBox(width: 8),
          _topPill('设置', false),
        ],
      ),
    );
  }

  Widget _tabStrip() {
    return Container(
      height: 54,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      color: const Color(0xFF181B27),
      child: Row(
        children: [
          Expanded(child: _tab('学习对标', Icons.link, true)),
          const SizedBox(width: 8),
          Expanded(child: _tab('全局素材', Icons.folder_copy_outlined, false)),
          const SizedBox(width: 8),
          Expanded(child: _tab('爆款口播视频制作', Icons.movie, false)),
          const Spacer(),
          TextButton.icon(
            onPressed: loadBootstrap,
            icon: const Icon(Icons.refresh),
            label: const Text('刷新'),
          ),
        ],
      ),
    );
  }

  Widget _leftPanel(String status, List<Map<String, dynamic>> steps) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionTitle('1. 提取视频文案'),
          Row(
            children: [
              Expanded(child: _input(urlController, '粘贴抖音分享链接')),
              const SizedBox(width: 8),
              _ghostButton('选择视频', uploadSourceVideo),
            ],
          ),
          const SizedBox(height: 8),
          _stepButton('1. 提取视频文案', createTask),
          const SizedBox(height: 8),
          _textBox(originalScriptController, '提取的原文案', 8),
          const SizedBox(height: 12),
          _sectionTitle('2. 一键仿写'),
          Row(
            children: [
              Expanded(child: _styleDropdown()),
              const SizedBox(width: 8),
              SizedBox(
                width: 110,
                child: _dropdown(
                  selectedWordCount,
                  const ['300字', '500字', '800字'],
                  (v) => setState(
                      () => selectedWordCount = v ?? selectedWordCount),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _stepButton('2. 一键仿写', rewrite),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _input(audienceController, '目标人群')),
              const SizedBox(width: 8),
              Expanded(child: _input(productController, '产品/服务')),
            ],
          ),
          const SizedBox(height: 8),
          _textBox(rewrittenScriptController, '改写后的文案', 8),
          const SizedBox(height: 8),
          _statusStrip(status, steps),
        ],
      ),
    );
  }

  Widget _centerPanel() {
    final voiceOptions =
        voices.map((v) => v['voice_id'] as String).toList(growable: true);
    if (!voiceOptions.contains(selectedVoice))
      voiceOptions.insert(0, selectedVoice);
    final voiceLabels = {
      for (final v in voices) v['voice_id'] as String: v['name'] as String,
    };
    final humanOptions = digitalHumans
        .map((h) => h['digital_human_id'] as String)
        .toList(growable: true);
    if (humanOptions.isEmpty) {
      humanOptions.add('');
    } else if (!humanOptions.contains(selectedDigitalHuman)) {
      humanOptions.insert(0, selectedDigitalHuman);
    }
    final humanLabels = {
      '': '未选择数字人视频',
      for (final h in digitalHumans)
        h['digital_human_id'] as String: h['name'] as String,
    };

    return SingleChildScrollView(
      padding: const EdgeInsets.all(10),
      child: Column(
        children: [
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeader('3. 声音生成', '声音服务：', '已启动'),
                const SizedBox(height: 12),
                _labeledSlider(
                  '语速',
                  speechRate,
                  0.6,
                  1.4,
                  (v) => setState(() => speechRate = v),
                  speechRate.toStringAsFixed(1),
                ),
                const SizedBox(height: 10),
                _formRow('声音', [
                  Expanded(
                    child: _dropdown(
                      selectedVoice,
                      voiceOptions,
                      (v) => setState(() => selectedVoice = v ?? selectedVoice),
                      labels: voiceLabels,
                    ),
                  ),
                  _ghostButton('上传声音', uploadVoice),
                  _stepButton('克隆声音', cloneVoice, compact: true),
                  _stepButton(
                    _isPlayingVoice ? '停止播放' : '播放声音',
                    playVoice,
                    compact: true,
                  ),
                ]),
              ],
            ),
          ),
          const SizedBox(height: 10),
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeader('4. 视频生成', '视频服务：', '已启动'),
                const SizedBox(height: 10),
                Row(
                  children: [
                    _modeChip('单形象', true),
                    const SizedBox(width: 8),
                    _modeChip('多镜头', false),
                    const Spacer(),
                    Text(
                      _engineStatusText(),
                      style: const TextStyle(
                        color: Colors.white70,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _formRow('数字人引擎', [
                  Expanded(child: _readonlyBox('高清模式')),
                ]),
                const SizedBox(height: 10),
                _formRow('数字人', [
                  Expanded(
                    child: _dropdown(
                      selectedDigitalHuman,
                      humanOptions,
                      (v) => selectDigitalHuman(v ?? ''),
                      labels: humanLabels,
                    ),
                  ),
                  _ghostButton('上传形象', uploadDigitalHuman),
                  _ghostButton('删除', () {}),
                  _stepButton(
                    renderingVideo ? '停止生成' : '生成视频',
                    renderingVideo ? stopRender : render,
                    compact: true,
                    allowWhileLoading: renderingVideo,
                  ),
                  _stepButton('预览视频', previewOutputVideo, compact: true),
                ]),
                const SizedBox(height: 10),
                Row(
                  children: [
                    const Text('牙齿高清'),
                    Switch(
                      value: toothHd,
                      onChanged: (v) => setState(() => toothHd = v),
                    ),
                    const Text('开启'),
                    const Spacer(),
                    const Text('动作随机'),
                    Switch(
                      value: randomMotion,
                      onChanged: (v) => setState(() => randomMotion = v),
                    ),
                    Text(randomMotion ? '开启' : '关闭'),
                  ],
                ),
                _readonlyBox(selectedDigitalHuman.isEmpty
                    ? '请上传或选择数字人素材'
                    : selectedDigitalHuman),
                const SizedBox(height: 10),
                _mouthApertureStatusCard(),
                const SizedBox(height: 10),
                _subTabs(),
                const SizedBox(height: 10),
                _mediaSubTabPanel(),
                const SizedBox(height: 8),
                _stepButton(
                  '5. 字幕/BGM/封面合成',
                  render,
                  allowWhileLoading: renderingVideo,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _rightPanel() {
    final sourceUrl = _sourceVideoUrl;
    final outputUrl = _outputVideoUrl;
    final title = task?['title'] as String? ?? '未生成';
    return SingleChildScrollView(
      padding: const EdgeInsets.all(10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionTitle('视频预览'),
          const SizedBox(height: 8),
          AspectRatio(
            aspectRatio: 9 / 16,
            child: Container(
              decoration: BoxDecoration(
                color: Colors.black,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: purpleLine.withValues(alpha: 0.5)),
              ),
              clipBehavior: Clip.antiAlias,
              child: outputUrl != null
                  ? _OutputVideoPreview(url: outputUrl)
                  : sourceUrl != null
                      ? _OutputVideoPreview(url: sourceUrl)
                      : _previewPlaceholder(),
            ),
          ),
          const SizedBox(height: 8),
          _outputFileBar(),
          const SizedBox(height: 12),
          _sectionTitle('6. 视频封面与预览'),
          const SizedBox(height: 8),
          Row(
            children: const [
              Icon(Icons.image_outlined),
              SizedBox(width: 6),
              Text('封面', style: TextStyle(fontWeight: FontWeight.w800)),
            ],
          ),
          const SizedBox(height: 8),
          _dropdown('暗色蒙版1', const ['暗色蒙版1', '亮色大字版', '人物居中版'], (_) {}),
          const SizedBox(height: 8),
          _readonlyBox('cover.png'),
          const SizedBox(height: 10),
          Text('视频标题：$title', style: const TextStyle(color: Colors.white70)),
          const SizedBox(height: 12),
          const Text('发布平台', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final platform in const [
                'douyin',
                'shipinhao',
                'kuaishou',
                'xiaohongshu',
              ])
                _PlatformChip(
                  label: _platformLabel(platform),
                  active: selectedPublishPlatform == platform,
                  onTap: () =>
                      setState(() => _selectPublisherPlatform(platform)),
                ),
            ],
          ),
          const SizedBox(height: 12),
          _publisherPanel(),
        ],
      ),
    );
  }

  Widget _outputFileBar() {
    final path = _outputVideoPath;
    final fileName = path == null || path.isEmpty
        ? '成品视频生成后自动关联'
        : path.split(RegExp(r'[\\/]')).last;
    return Row(
      children: [
        Expanded(child: _readonlyBox(fileName)),
        const SizedBox(width: 8),
        _ghostButton('打开', openOutputVideo),
        const SizedBox(width: 8),
        _ghostButton('预览', previewOutputVideo),
      ],
    );
  }

  Widget _publisherPanel() {
    const platformOptions = ['douyin', 'kuaishou', 'xiaohongshu', 'shipinhao'];
    final visibleAccounts = publisherAccounts
        .where((account) => account['platform'] == selectedPublishPlatform)
        .toList(growable: false);
    final accountOptions = visibleAccounts
        .map((account) => account['account_id'] as String)
        .toList(growable: true);
    if (accountOptions.isEmpty) accountOptions.add('');
    final accountLabels = {
      '': '请选择发布账号',
      for (final account in visibleAccounts)
        account['account_id'] as String:
            '${_accountDisplayName(account)} / ${_accountStatusLabel(account['status'] as String? ?? '')}',
    };
    final selectedAccount = accountOptions.contains(selectedPublisherAccount)
        ? selectedPublisherAccount
        : accountOptions.first;
    final videoPath = _outputVideoPath ?? '成品视频生成后自动关联';

    return _panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '7. 视频发布',
                  style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
                ),
              ),
              IconButton(
                tooltip: '刷新账号和发布任务',
                onPressed: loadPublisherAccounts,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text('视频地址', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(child: _readonlyBox(videoPath)),
              const SizedBox(width: 8),
              _ghostButton('打开', openOutputVideo),
            ],
          ),
          const SizedBox(height: 10),
          const Text('账号管理', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _dropdown(
                  selectedPublishPlatform,
                  platformOptions,
                  (v) => setState(() {
                    _selectPublisherPlatform(v ?? selectedPublishPlatform);
                  }),
                  labels: {
                    for (final platform in platformOptions)
                      platform: _platformLabel(platform),
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                  child: _readonlyBox(publisherNicknameController.text.isEmpty
                      ? '登录后自动识别'
                      : publisherNicknameController.text)),
              const SizedBox(width: 8),
              _ghostButton('添加账号', createPublisherAccount),
            ],
          ),
          const SizedBox(height: 8),
          const Text('发布账号', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _dropdown(
                  selectedAccount,
                  accountOptions,
                  (v) => setState(() {
                    selectedPublisherAccount = v ?? '';
                    _syncPublisherNicknameField(publisherAccounts);
                  }),
                  labels: accountLabels,
                ),
              ),
              const SizedBox(width: 8),
              _ghostButton('登录', loginPublisherAccount),
              const SizedBox(width: 8),
              _ghostButton('检测', checkPublisherSession),
            ],
          ),
          const SizedBox(height: 12),
          const Text('发布方式', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          _publishModeSelector(),
          const SizedBox(height: 12),
          Row(
            children: [
              const Expanded(
                child: Text(
                  '发布内容',
                  style: TextStyle(fontWeight: FontWeight.w900),
                ),
              ),
              _ghostButton(
                generatingPublishContent ? '生成中' : 'AI生成',
                generatingPublishContent
                    ? () {}
                    : () => generatePublishContent(),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _input(publishTitleController, '视频标题（20字以内）', maxLength: 20),
          const SizedBox(height: 8),
          _textBox(publishBodyController, '发布文案', 4),
          const SizedBox(height: 8),
          _input(publishTopicsController, '话题，用空格、逗号或 # 分隔'),
          const SizedBox(height: 8),
          _stepButton(
            publishing ? '发布任务创建中...' : '创建发布任务',
            createPublishJobs,
            allowWhileLoading: publishing,
          ),
          if (publishJobs.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('最近发布任务', style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            for (final job in publishJobs)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    Icon(
                      _jobIcon(job['status'] as String? ?? ''),
                      size: 16,
                      color: _jobColor(job['status'] as String? ?? ''),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '${_platformLabel(job['platform'] as String? ?? '')}：${_jobStatusLabel(job['status'] as String? ?? '')}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _publishModeSelector() {
    return Row(
      children: [
        Expanded(
          child:
              _publishModeChip('direct', '直接发布', Icons.cloud_upload_outlined),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _publishModeChip('draft', '草稿', Icons.edit_note_outlined),
        ),
      ],
    );
  }

  Widget _publishModeChip(String value, String label, IconData icon) {
    final active = selectedPublishMode == value;
    return InkWell(
      onTap: () => setState(() => selectedPublishMode = value),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 42,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active ? const Color(0xFF25315A) : panelBg2,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: active ? cyan : purpleLine.withValues(alpha: 0.45),
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 17, color: active ? cyan : Colors.white54),
            const SizedBox(width: 6),
            Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
          ],
        ),
      ),
    );
  }

  String _platformLabel(String platform) {
    return switch (platform) {
      'douyin' => '抖音',
      'kuaishou' => '快手',
      'xiaohongshu' => '小红书',
      'shipinhao' => '视频号',
      _ => platform,
    };
  }

  String _accountStatusLabel(String status) {
    return switch (status) {
      'created' => '已创建',
      'login_opened' => '登录中',
      'logged_in' => '已登录',
      'needs_login' => '待登录',
      'needs_user_action' => '需人工处理',
      'expired' => '已过期',
      'failed' => '失败',
      _ => status,
    };
  }

  String _accountDisplayName(Map<String, dynamic> account) {
    final nickname = (account['nickname'] as String? ?? '').trim();
    if (nickname.isNotEmpty) return nickname;
    return '登录后自动识别';
  }

  String _jobStatusLabel(String status) {
    return switch (status) {
      'queued' => '排队中',
      'running' => '执行中',
      'published' => '已发布',
      'drafted' => '已存草稿',
      'needs_user_action' => '需人工处理',
      'failed' => '失败',
      _ => status,
    };
  }

  IconData _jobIcon(String status) {
    return switch (status) {
      'published' => Icons.check_circle,
      'drafted' => Icons.task_alt,
      'running' => Icons.sync,
      'queued' => Icons.schedule,
      'needs_user_action' => Icons.person_pin_circle_outlined,
      'failed' => Icons.error_outline,
      _ => Icons.info_outline,
    };
  }

  Color _jobColor(String status) {
    return switch (status) {
      'published' => const Color(0xFF55E6A5),
      'drafted' => const Color(0xFF55E6A5),
      'running' => cyan,
      'queued' => Colors.white60,
      'needs_user_action' => const Color(0xFFFFC857),
      'failed' => const Color(0xFFFF7A9B),
      _ => Colors.white60,
    };
  }

  String _engineStatusText() {
    final heygemOnline = providers?['heygem_online'] == true;
    if (heygemOnline) return '云服务：已开启';
    return '云服务：未开启';
  }

  Widget _mouthApertureStatusCard() {
    final online = providers?['heygem_online'] == true;
    final color = online ? const Color(0xFF55E6A5) : const Color(0xFFFFC857);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF171B2B),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.55)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                online ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
                color: color,
                size: 18,
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  online ? '云服务：已开启' : '云服务：未开启',
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  double _providerDoubleFrom(
    Map<String, dynamic>? source,
    String key, {
    required double fallback,
    double? zeroFallback,
  }) {
    final value = source?[key];
    if (value is num) {
      final number = value.toDouble();
      if (number == 0 && zeroFallback != null) return zeroFallback;
      return number;
    }
    final parsed = double.tryParse(value?.toString() ?? '');
    if (parsed == null) return fallback;
    if (parsed == 0 && zeroFallback != null) return zeroFallback;
    return parsed;
  }

  Widget _messageBar() {
    final bgColor =
        messageIsError ? const Color(0xFF3A1420) : const Color(0xFF123B2A);
    final textColor =
        messageIsError ? const Color(0xFFFFB0C2) : const Color(0xFFB9F8D0);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      color: bgColor,
      child: Text(message, style: TextStyle(color: textColor)),
    );
  }

  Widget _panel({required Widget child}) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: panelBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: purpleLine.withValues(alpha: 0.35)),
      ),
      child: child,
    );
  }

  Widget _sectionHeader(String title, String label, String value) {
    return Row(
      children: [
        Text(title,
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
        const Spacer(),
        Text(label,
            style: const TextStyle(
                color: Colors.white70, fontWeight: FontWeight.w800)),
        Text(value,
            style: const TextStyle(
                color: Color(0xFF55E6A5), fontWeight: FontWeight.w900)),
      ],
    );
  }

  Widget _sectionTitle(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(text,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
    );
  }

  Widget _formRow(String label, List<Widget> children) {
    return Row(
      children: [
        SizedBox(
          width: 88,
          child: Text(label,
              style: const TextStyle(
                  color: Colors.white70, fontWeight: FontWeight.w800)),
        ),
        for (var i = 0; i < children.length; i++) ...[
          children[i],
          if (i != children.length - 1) const SizedBox(width: 8),
        ],
      ],
    );
  }

  Widget _styleDropdown() {
    final options =
        rewriteStyles.map((s) => s['name'] as String).toList(growable: true);
    if (options.isEmpty) options.addAll(const ['同款口播', '带货', '种草']);
    if (!options.contains(selectedStyle)) options.insert(0, selectedStyle);
    return _dropdown(
      selectedStyle,
      options,
      (v) => setState(() => selectedStyle = v ?? selectedStyle),
    );
  }

  Widget _dropdown(
    String value,
    List<String> options,
    ValueChanged<String?> onChanged, {
    Map<String, String> labels = const {},
  }) {
    final safeOptions = options.isEmpty ? [''] : options;
    final safeValue = safeOptions.contains(value) ? value : safeOptions.first;
    return DropdownButtonFormField<String>(
      initialValue: safeValue,
      isExpanded: true,
      decoration: _inputDecoration(''),
      items: safeOptions
          .map(
            (item) => DropdownMenuItem(
              value: item,
              child: Text(
                labels[item] ?? item,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          )
          .toList(),
      onChanged: onChanged,
    );
  }

  Widget _input(
    TextEditingController controller,
    String hint, {
    int? maxLength,
  }) {
    return TextField(
      controller: controller,
      inputFormatters: maxLength == null
          ? null
          : [LengthLimitingTextInputFormatter(maxLength)],
      decoration: _inputDecoration(hint),
    );
  }

  Widget _textBox(TextEditingController controller, String hint, int lines) {
    return TextField(
      controller: controller,
      minLines: lines,
      maxLines: lines,
      decoration: _inputDecoration(hint),
    );
  }

  InputDecoration _inputDecoration(String hint) {
    return InputDecoration(
      hintText: hint.isEmpty ? null : hint,
      filled: true,
      fillColor: panelBg2,
      isDense: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(7)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: BorderSide(color: purpleLine.withValues(alpha: 0.45)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: const BorderSide(color: cyan, width: 1.2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    );
  }

  Widget _stepButton(
    String text,
    VoidCallback onPressed, {
    bool compact = false,
    bool allowWhileLoading = false,
  }) {
    final disabled = loading && !allowWhileLoading;
    final child = DecoratedBox(
      decoration: BoxDecoration(
        gradient: disabled ? null : const LinearGradient(colors: [cyan, pink]),
        color: disabled ? Colors.white12 : null,
        borderRadius: BorderRadius.circular(8),
      ),
      child: ElevatedButton(
        onPressed: disabled ? null : onPressed,
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: Colors.transparent,
          shadowColor: Colors.transparent,
          foregroundColor: Colors.white,
          disabledBackgroundColor: Colors.transparent,
          disabledForegroundColor: Colors.white54,
          minimumSize: Size(compact ? 96 : 0, 42),
          padding: EdgeInsets.symmetric(horizontal: compact ? 12 : 18),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w900)),
      ),
    );
    return compact ? child : SizedBox(width: double.infinity, child: child);
  }

  Widget _ghostButton(String text, VoidCallback onPressed) {
    return OutlinedButton(
      onPressed: loading ? null : onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: Colors.white,
        side: BorderSide(color: purpleLine.withValues(alpha: 0.8)),
        backgroundColor: panelBg2,
        minimumSize: const Size(72, 40),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      child: Text(text, style: const TextStyle(fontWeight: FontWeight.w800)),
    );
  }

  Widget _modeChip(String text, bool active) {
    return Container(
      height: 38,
      padding: const EdgeInsets.symmetric(horizontal: 18),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: active ? const Color(0xFF25315A) : panelBg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color: active ? cyan : purpleLine.withValues(alpha: 0.55)),
      ),
      child: Text(text, style: const TextStyle(fontWeight: FontWeight.w900)),
    );
  }

  Widget _topPill(String text, bool active) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 11),
      decoration: BoxDecoration(
        gradient: active ? const LinearGradient(colors: [cyan, pink]) : null,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: purpleLine),
      ),
      child: Text(text, style: const TextStyle(fontWeight: FontWeight.w900)),
    );
  }

  Widget _tab(String text, IconData icon, bool active) {
    return Container(
      height: 38,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: active ? const Color(0xFF261F3E) : panelBg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: active ? purpleLine : Colors.white12),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon,
              size: 17,
              color: active ? const Color(0xFFD4A4FF) : Colors.white54),
          const SizedBox(width: 8),
          Text(text, style: const TextStyle(fontWeight: FontWeight.w900)),
        ],
      ),
    );
  }

  Widget _readonlyBox(String text) {
    return Container(
      height: 42,
      alignment: Alignment.centerLeft,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: panelBg2,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: purpleLine.withValues(alpha: 0.4)),
      ),
      child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis),
    );
  }

  Widget _mediaSubTabPanel() {
    return switch (selectedMediaSubTab) {
      'bgm' => _bgmPanel(),
      'video' => _videoSubPanel(),
      _ => _subtitlePanel(),
    };
  }

  Widget _videoSubPanel() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
                child: _readonlyBox(selectedDigitalHuman.isEmpty
                    ? '请上传或选择数字人素材'
                    : selectedDigitalHuman)),
            const SizedBox(width: 8),
            _ghostButton('选择视频', uploadSourceVideo),
          ],
        ),
      ],
    );
  }

  Widget _bgmPanel() {
    final options = [
      'none',
      ...(bgmTracks.isEmpty
          ? const ['default-light', 'default-tech', 'default-warm']
          : bgmTracks.map((item) => item['bgm_id'].toString())),
    ];
    final names = {
      'none': '无背景音乐',
      for (final item in bgmTracks)
        item['bgm_id'].toString():
            item['name']?.toString() ?? item['bgm_id'].toString()
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: _dropdown(
                selectedBgm,
                options,
                (value) {
                  if (value == null) return;
                  setState(() => selectedBgm = value);
                },
                labels: names,
              ),
            ),
            const SizedBox(width: 8),
            _ghostButton('上传BGM', uploadBgm),
          ],
        ),
        const SizedBox(height: 10),
        _labeledSlider(
          'BGM音量',
          bgmVolume,
          0,
          0.6,
          (v) => setState(() => bgmVolume = v),
          '${(bgmVolume * 100).round()}%',
        ),
        const SizedBox(height: 4),
        Text(
          selectedBgm == 'none'
              ? '最终视频不会混入背景音乐。'
              : selectedBgm.startsWith('custom:')
                  ? '将使用你上传的背景音乐，并按音量混入最终视频。'
                  : '将使用内置循环背景音乐，并按音量混入最终视频。',
          style: const TextStyle(color: Colors.white60, fontSize: 12),
        ),
      ],
    );
  }

  Widget _subtitlePanel() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(child: _readonlyBox('字幕文件将自动生成')),
            const SizedBox(width: 8),
            _stepButton('生成字幕', render, compact: true),
            const SizedBox(width: 8),
            _ghostButton('编辑字幕及画中画', () {}),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Checkbox(
              value: true,
              onChanged: (_) {},
            ),
            const Text('字幕 启用'),
            const SizedBox(width: 12),
            Expanded(child: _readonlyBox('免费 特粗')),
            const SizedBox(width: 8),
            _ghostButton('刷新', () {}),
            const SizedBox(width: 8),
            const Text('字幕颜色'),
            const SizedBox(width: 8),
            _colorSquare(Colors.black),
            const SizedBox(width: 8),
            const Text('描边颜色'),
            const SizedBox(width: 8),
            _colorSquare(Colors.white),
          ],
        ),
        _labeledSlider(
          '字号',
          subtitleSize,
          12,
          56,
          (v) => setState(() => subtitleSize = v),
          subtitleSize.round().toString(),
        ),
      ],
    );
  }

  Widget _subTabs() {
    const items = [
      ('video', Icons.movie_outlined, '视频'),
      ('bgm', Icons.music_note, '背景音乐'),
      ('subtitles', Icons.closed_caption_outlined, '字幕及画中画'),
    ];
    return Row(
      children: items
          .map(
            (item) => Expanded(
              child: InkWell(
                onTap: () => setState(() => selectedMediaSubTab = item.$1),
                child: Container(
                  height: 42,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    border: Border(
                      bottom: BorderSide(
                        color: selectedMediaSubTab == item.$1
                            ? const Color(0xFFD4A4FF)
                            : const Color(0xFF414866),
                        width: selectedMediaSubTab == item.$1 ? 2 : 1,
                      ),
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(item.$2, size: 17, color: const Color(0xFFBFA8FF)),
                      const SizedBox(width: 6),
                      Text(item.$3,
                          style: const TextStyle(fontWeight: FontWeight.w800)),
                    ],
                  ),
                ),
              ),
            ),
          )
          .toList(),
    );
  }

  Map<String, dynamic>? _activeProgressStep(Map<String, dynamic>? currentTask) {
    final steps = (currentTask?['progress_steps'] as List?)
            ?.cast<Map<String, dynamic>>() ??
        const [];
    for (final step in steps) {
      if (step['status'] == 'running') return step;
    }
    return null;
  }

  double _progressPercent(List<Map<String, dynamic>> steps) {
    if (steps.isEmpty) return 0;
    final completed =
        steps.where((step) => step['status'] == 'completed').length;
    final running = steps.any((step) => step['status'] == 'running') ? 0.35 : 0;
    return ((completed + running) / steps.length).clamp(0, 1).toDouble();
  }

  String _statusText(String status) {
    return switch (status) {
      'created' => '已创建',
      'imported' => '已导入',
      'transcribed' => '已提取文案',
      'rewritten' => '已完成仿写',
      'rendering' => '视频生成中',
      'completed' => '已完成',
      'failed' => '已失败',
      _ => status,
    };
  }

  String _stepStatusText(String status) {
    return switch (status) {
      'completed' => '完成',
      'running' => '进行中',
      'failed' => '失败',
      _ => '等待',
    };
  }

  Widget _statusStrip(String status, List<Map<String, dynamic>> steps) {
    final percent = _progressPercent(steps);
    final active = _activeProgressStep(task);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF171A28),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: purpleLine.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_mode, size: 18, color: Color(0xFFD4A4FF)),
              const SizedBox(width: 7),
              Expanded(
                child: Text('智能体制作进度：${_statusText(status)}',
                    style: const TextStyle(fontWeight: FontWeight.w900)),
              ),
              Text('${(percent * 100).round()}%',
                  style: const TextStyle(
                      color: Color(0xFF55E6A5), fontWeight: FontWeight.w900)),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: percent == 0 && status == 'rendering' ? null : percent,
              minHeight: 8,
              backgroundColor: Colors.white10,
              color: active == null ? cyan : const Color(0xFF55E6A5),
            ),
          ),
          if (active != null) ...[
            const SizedBox(height: 8),
            Text('正在处理：${active['label']}',
                style: const TextStyle(
                    color: Color(0xFF55E6A5), fontWeight: FontWeight.w800)),
          ],
          const SizedBox(height: 8),
          for (final step in steps.take(9))
            Row(
              children: [
                Icon(
                  step['status'] == 'completed'
                      ? Icons.check_circle
                      : step['status'] == 'running'
                          ? Icons.timelapse
                          : Icons.radio_button_unchecked,
                  size: 15,
                  color: step['status'] == 'completed' ? cyan : Colors.white38,
                ),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                      '${step['label']} · ${_stepStatusText(step['status'] as String? ?? '')}',
                      style: const TextStyle(fontSize: 12)),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _labeledSlider(
    String label,
    double value,
    double min,
    double max,
    ValueChanged<double> onChanged,
    String trailing,
  ) {
    return Row(
      children: [
        SizedBox(width: 72, child: Text(label)),
        Expanded(
          child: Slider(value: value, min: min, max: max, onChanged: onChanged),
        ),
        SizedBox(width: 44, child: Text(trailing, textAlign: TextAlign.right)),
      ],
    );
  }

  Widget _colorSquare(Color color) {
    return Container(
      width: 34,
      height: 34,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: purpleLine.withValues(alpha: 0.45)),
      ),
    );
  }

  Widget _previewPlaceholder() {
    return Stack(
      fit: StackFit.expand,
      children: [
        Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Color(0xFF26315C), Color(0xFF151827)],
            ),
          ),
        ),
        const Center(
            child: Icon(Icons.person, size: 88, color: Colors.white70)),
        const Align(
          alignment: Alignment.bottomCenter,
          child: Padding(
            padding: EdgeInsets.all(18),
            child: Text(
              '成品视频预览',
              style: TextStyle(fontWeight: FontWeight.w900),
            ),
          ),
        ),
      ],
    );
  }
}

class _PlatformChip extends StatelessWidget {
  final String label;
  final bool active;
  final VoidCallback? onTap;

  const _PlatformChip({
    required this.label,
    required this.active,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: active ? const Color(0xFF2D2A52) : const Color(0xFF202334),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: active ? _WorkbenchPageState.pink : Colors.white24,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                active ? Icons.check_circle : Icons.radio_button_unchecked,
                size: 16,
                color: active ? _WorkbenchPageState.pink : Colors.white38,
              ),
              const SizedBox(width: 5),
              Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
            ],
          ),
        ),
      ),
    );
  }
}

class _OutputVideoPreview extends StatefulWidget {
  final String url;

  const _OutputVideoPreview({required this.url});

  @override
  State<_OutputVideoPreview> createState() => _OutputVideoPreviewState();
}

class _OutputVideoPreviewState extends State<_OutputVideoPreview> {
  late final Player _player;
  late final VideoController _controller;

  @override
  void initState() {
    super.initState();
    _player = Player();
    _controller = VideoController(_player);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _player.open(Media(widget.url), play: false);
    });
  }

  @override
  void didUpdateWidget(covariant _OutputVideoPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _player.open(Media(widget.url), play: false);
      });
    }
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Video(controller: _controller, fit: BoxFit.contain);
  }
}

class _VideoPlayerDialog extends StatefulWidget {
  final String url;

  const _VideoPlayerDialog({required this.url});

  @override
  State<_VideoPlayerDialog> createState() => _VideoPlayerDialogState();
}

class _VideoPlayerDialogState extends State<_VideoPlayerDialog> {
  late final Player _player;
  late final VideoController _controller;

  @override
  void initState() {
    super.initState();
    _player = Player();
    _controller = VideoController(_player);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _player.open(Media(widget.url));
    });
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF11131B),
      insetPadding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980, maxHeight: 720),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 8, 8),
              child: Row(
                children: [
                  const Text('预览视频',
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                  const Spacer(),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Flexible(
              child: AspectRatio(
                aspectRatio: 9 / 16,
                child: Video(controller: _controller, fit: BoxFit.contain),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
