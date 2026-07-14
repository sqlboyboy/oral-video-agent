import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

part 'mobile.dart';
part 'mobile_updater.dart';

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
        fontFamilyFallback: const [
          'Microsoft YaHei UI',
          'Microsoft YaHei',
          'PingFang SC',
        ],
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF8B5CF6),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF0E0F18),
        dividerColor: const Color(0xFF2B2E42),
        cardTheme: CardThemeData(
          color: const Color(0xFF181A27),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: const BorderSide(color: Color(0xFF2D3044)),
          ),
        ),
        tooltipTheme: const TooltipThemeData(
          waitDuration: Duration(milliseconds: 350),
        ),
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

class _BootstrapResult {
  const _BootstrapResult(this.apiBase, this.body);

  final String apiBase;
  final Map<String, dynamic> body;
}

class _CloudUploadFile {
  const _CloudUploadFile({
    required this.kind,
    required this.file,
    required this.fileName,
    required this.contentType,
  });

  final String kind;
  final File file;
  final String fileName;
  final String contentType;
}

enum _WorkspaceSection {
  studio,
  voices,
  avatars,
  media,
  tasks,
  accounts,
  cloudAccount,
}

class _WorkbenchPageState extends State<WorkbenchPage> {
  static const _defaultApiBase = 'http://127.0.0.1:8000';
  static const _configuredApiBase =
      String.fromEnvironment('API_BASE', defaultValue: _defaultApiBase);
  static const _fallbackApiBase = 'http://127.0.0.1:8001';
  static const _configuredCloudApiBase = String.fromEnvironment(
    'CLOUD_API_BASE',
    defaultValue: 'https://api.example.com',
  );
  static const _allowInsecureCloudHttp = bool.fromEnvironment(
    'ALLOW_INSECURE_CLOUD_HTTP',
    defaultValue: false,
  );
  static const _secureActivationTokenKey = 'cloud_activation_token_v1';
  static const _secureDeviceTokenKey = 'cloud_device_token_v1';
  static const cyan = Color(0xFF2F9BFF);
  static const pink = Color(0xFFE260D4);
  static const panelBg = Color(0xFF1D2030);
  static const panelBg2 = Color(0xFF24283A);
  static const purpleLine = Color(0xFF7E54E8);
  static const studioPrimary = Color(0xFF5B5CEB);
  static const studioPrimaryDark = Color(0xFF4546D7);
  static const studioCanvas = Color(0xFFF4F6FA);
  static const studioBorder = Color(0xFFE7EAF0);
  static const studioInk = Color(0xFF161A2B);
  static const studioMuted = Color(0xFF7B8194);
  static const studioSuccess = Color(0xFF2BB673);
  static const _subtitleFontOptions = [
    'Microsoft YaHei',
    'Microsoft YaHei UI',
    'SimHei',
    'SimSun',
    'KaiTi',
    'Arial',
  ];
  static const _subtitleFontLabels = {
    'Microsoft YaHei': '微软雅黑',
    'Microsoft YaHei UI': '微软雅黑 UI',
    'SimHei': '黑体',
    'SimSun': '宋体',
    'KaiTi': '楷体',
    'Arial': 'Arial',
  };
  static const _pipPositionOptions = [
    'top_right',
    'fullscreen',
    'custom',
    'top_left',
    'bottom_right',
    'bottom_left',
    'center',
  ];
  static const _pipTimingOptions = [
    'full',
    'time',
    'sentence',
  ];
  static const _pipPositionLabels = {
    'top_right': '右上角',
    'top_left': '左上角',
    'bottom_right': '右下角',
    'bottom_left': '左下角',
    'center': '居中',
    'fullscreen': '全屏',
    'custom': '自定义拖放',
  };
  static const _pipTimingLabels = {
    'full': '全程显示',
    'time': '按秒数显示',
    'sentence': '按句子显示',
  };
  static const _pipCanvasAspectRatio = 9 / 16;
  static const _pipMediaAspectRatio = 16 / 9;
  static const _pipMarginX = 24 / 1080;
  static const _pipMarginY = 24 / 1920;
  static const _publisherNicknamePlaceholder = '登录后自动识别';

  final urlController = TextEditingController();
  final productController = TextEditingController();
  final audienceController = TextEditingController();
  final originalScriptController = TextEditingController();
  final rewrittenScriptController = TextEditingController();
  final publisherNicknameController = TextEditingController();
  final publishTitleController = TextEditingController();
  final publishBodyController = TextEditingController();
  final publishTopicsController = TextEditingController();
  final cloudApiController =
      TextEditingController(text: _configuredCloudApiBase);
  final cloudEmailController = TextEditingController();
  final cloudEmailCodeController = TextEditingController();
  final cloudPasswordController = TextEditingController();
  final cloudPasswordConfirmController = TextEditingController();
  final cloudActivationCodeController = TextEditingController();
  final cloudDurationController = TextEditingController(text: '600');
  final pipStartController = TextEditingController(text: '0');
  final pipEndController = TextEditingController();
  final pipTriggerController = TextEditingController();
  Map<String, dynamic>? task;
  Map<String, dynamic>? providers;
  Map<String, dynamic>? output;
  Map<String, dynamic>? cloudSession;
  Map<String, dynamic>? cloudWallet;
  Map<String, dynamic>? cloudJob;
  Map<String, dynamic>? cloudDouyinTranscription;
  Map<String, dynamic>? cloudEstimate;
  Map<String, dynamic>? mouthAtlasDiagnosis;
  List<Map<String, dynamic>> cloudLedger = const [];
  List<Map<String, dynamic>> rewriteStyles = const [];
  List<Map<String, dynamic>> voices = const [];
  List<Map<String, dynamic>> digitalHumans = const [];
  List<Map<String, dynamic>> bgmTracks = const [];
  List<Map<String, dynamic>> publisherAccounts = const [];
  List<Map<String, dynamic>> publishJobs = const [];
  List<Map<String, dynamic>> taskHistory = const [];
  List<Map<String, dynamic>> mobileCloudJobs = const [];
  bool loading = false;
  bool renderingVideo = false;
  bool diagnosingMouthAtlas = false;
  bool publishing = false;
  bool generatingPublishContent = false;
  bool loadingTaskHistory = false;
  bool batchDeletingTasks = false;
  bool cloudVoiceCancelRequested = false;
  bool localApiOnline = false;
  bool cloudAccountSignedOut = false;
  bool cloudPasswordVisible = false;
  bool cloudPasswordConfirmVisible = false;
  bool initialized = false;
  String apiBase = _configuredApiBase;
  String message = '';
  bool messageIsError = false;
  String publishContentGeneratedKey = '';
  String generationMode = 'cloud';
  String cloudActivationToken = '';
  bool cloudActivationValid = false;
  String cloudDeviceToken = '';
  String cloudSourceVideoPath = '';
  String cloudSourceVideoName = '';
  String cloudOutputUrl = '';
  String cloudOutputLocalPath = '';
  String cloudVoiceAudioPath = '';
  String mobileVoiceReferencePath = '';
  String mobileVoiceReferenceName = '';
  String mobileDigitalHumanPath = '';
  String mobileDigitalHumanName = '';
  String cloudVoiceJobId = '';
  String generatedVoiceKey = '';
  String coverPath = '';
  String selectedStyle = '同款口播';
  String selectedVoice = '';
  String selectedBgm = 'none';
  String selectedDigitalHuman = '';
  String selectedDigitalHumanEngine = 'heygem-local';
  String selectedPublishPlatform = 'douyin';
  String selectedPublisherAccount = '';
  String selectedPublishMode = 'direct';
  String selectedMediaSubTab = 'subtitles';
  _WorkspaceSection selectedSection = _WorkspaceSection.studio;
  String taskStatusFilter = 'all';
  String cloudAuthMode = 'login';
  int mobileNavigationIndex = 0;
  bool mobileUpdateChecking = false;
  String mobileAppVersion = '';
  int studioStep = 0;
  final Set<String> selectedTaskIds = <String>{};
  bool toothHd = true;
  bool randomMotion = false;
  bool mouthApertureEnabled = true;
  double speechRate = 1.0;
  double voicePreviewVolume = 0.45;
  double bgmVolume = 0.35;
  double subtitleSize = 12;
  bool subtitlesEnabled = true;
  String selectedSubtitleFont = 'Microsoft YaHei';
  Color subtitleColor = const Color(0xFFFFE600);
  Color subtitleOutlineColor = const Color(0xFF000000);
  List<String> subtitlePreviewLines = const [];
  bool pipEnabled = false;
  String pipAssetId = '';
  String pipAssetName = '';
  String pipAssetPath = '';
  String pipPosition = 'top_right';
  String pipTimingMode = 'full';
  double pipScale = 0.28;
  double pipX = 0.70;
  double pipY = 0.03;
  double mouthApertureStrength = 0.50;
  double mouthApertureEnergyThreshold = 0.24;
  double mouthApertureMinRatio = 0.07;
  double mouthApertureMaxRatio = 0.36;
  double mouthApertureAttack = 1.0;
  double mouthApertureRelease = 1.0;
  int outputRefresh = 0;
  Timer? renderPollTimer;
  Timer? cloudPollTimer;
  Timer? cloudEmailCodeTimer;
  int cloudEmailCodeCooldown = 0;
  Process? _localApiProcess;
  Player? _voicePlayer;
  Player? _originalAudioPlayer;
  Player? _bgmPlayer;
  bool _isPlayingVoice = false;
  bool _isPlayingOriginalAudio = false;
  bool _isPlayingBgm = false;

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  @override
  void dispose() {
    renderPollTimer?.cancel();
    cloudPollTimer?.cancel();
    cloudEmailCodeTimer?.cancel();
    _localApiProcess?.kill();
    _voicePlayer?.dispose();
    _originalAudioPlayer?.dispose();
    _bgmPlayer?.dispose();
    urlController.dispose();
    productController.dispose();
    audienceController.dispose();
    originalScriptController.dispose();
    rewrittenScriptController.dispose();
    publisherNicknameController.dispose();
    publishTitleController.dispose();
    publishBodyController.dispose();
    publishTopicsController.dispose();
    cloudApiController.dispose();
    cloudEmailController.dispose();
    cloudEmailCodeController.dispose();
    cloudPasswordController.dispose();
    cloudPasswordConfirmController.dispose();
    cloudActivationCodeController.dispose();
    cloudDurationController.dispose();
    pipStartController.dispose();
    pipEndController.dispose();
    pipTriggerController.dispose();
    super.dispose();
  }

  Future<void> loadBootstrap() async {
    try {
      final bootstrap = await _loadBootstrapFromAvailableApi();
      final loadedApiBase = bootstrap.apiBase;
      final body = bootstrap.body;
      final loadedVoices =
          (body['voices'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
      final loadedHumans =
          (body['digital_humans'] as List?)?.cast<Map<String, dynamic>>() ??
              const [];
      final loadedBgm =
          (body['bgm'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
      if (!mounted) return;
      setState(() {
        localApiOnline = true;
        final apiBaseChanged = apiBase != loadedApiBase;
        apiBase = loadedApiBase;
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
        final voiceIds = _limitedProfileOptions(loadedVoices, 'voice_id',
            preferredSystemPrefix: 'clone:');
        if (!voiceIds.contains(selectedVoice) && voiceIds.isNotEmpty) {
          selectedVoice = voiceIds.first;
        }
        final humanIds = loadedHumans
            .where((v) => v['built_in'] != true)
            .map((v) => v['digital_human_id'] as String)
            .toList();
        if (!humanIds.contains(selectedDigitalHuman)) {
          selectedDigitalHuman = humanIds.isEmpty ? '' : humanIds.first;
        }
        final bgmIds = _effectiveBgmOptionsFor(loadedBgm).toSet();
        if (selectedBgm != 'none' && !bgmIds.contains(selectedBgm)) {
          selectedBgm = 'none';
        }
        if (rewriteStyles.isNotEmpty &&
            !rewriteStyles.any((s) => s['name'] == selectedStyle)) {
          selectedStyle = rewriteStyles.first['name'] as String;
        }
        if (apiBaseChanged && message.isEmpty) {
          message = '已连接本项目后端：$loadedApiBase';
          messageIsError = false;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        localApiOnline = false;
        message = e.toString();
        messageIsError = true;
      });
    }
  }

  Future<void> _initialize() async {
    if (_isAndroidClient) {
      generationMode = 'cloud';
      subtitlesEnabled = false;
      cloudDurationController.text = '60';
      await _loadMobilePackageVersion();
      await _loadCloudAuth();
      if (_cloudLoggedIn) {
        await loadCloudMe(silent: true);
        await loadCloudLedger(silent: true);
        await loadMobileCloudJobs(silent: true);
      }
      if (!mounted) return;
      setState(() => initialized = true);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_checkForMobileUpdate(silent: true));
      });
      return;
    }
    await loadBootstrap();
    await loadTaskHistory(silent: true);
    await _resetReleaseLocalStateIfNeeded();
    await _loadCloudAuth();
    if (_cloudLicensed && !cloudAccountSignedOut) {
      await loadCloudLedger(silent: true);
    }
    if (mounted && providers != null) {
      await loadPublisherAccounts();
    }
    if (!mounted) return;
    setState(() => initialized = true);
  }

  Future<File> _releaseResetMarkerFile() async {
    final dir = await getApplicationSupportDirectory();
    await dir.create(recursive: true);
    return File('${dir.path}${Platform.pathSeparator}release_reset_v1.json');
  }

  Future<void> _resetReleaseLocalStateIfNeeded() async {
    try {
      final marker = await _releaseResetMarkerFile();
      if (await marker.exists()) return;

      await _clearCloudAuth();

      final res = await http
          .post(Uri.parse('$apiBase/api/publisher/reset-local-state'))
          .timeout(const Duration(seconds: 8));
      _check(res);

      if (mounted) {
        setState(() {
          publisherAccounts = const [];
          publishJobs = const [];
          selectedPublisherAccount = '';
          publisherNicknameController.clear();
        });
      }
      await marker.writeAsString(
        jsonEncode({'reset_at': DateTime.now().toIso8601String()}),
      );
    } catch (_) {
      // 老后端没有重置接口时保持静默；升级后会在下次启动继续尝试?    }
    }
  }

  String get _cloudApiBase {
    final value = cloudApiController.text.trim();
    var base = value.isEmpty ? _configuredCloudApiBase : value;
    if (_isAndroidClient && !_isSecureCloudBase(base)) {
      base = _configuredCloudApiBase;
    }
    return base.endsWith('/') ? base.substring(0, base.length - 1) : base;
  }

  bool _isSecureCloudBase(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null || !uri.hasAuthority) return false;
    if (uri.scheme.toLowerCase() == 'https') return true;
    return kDebugMode &&
        _allowInsecureCloudHttp &&
        uri.scheme.toLowerCase() == 'http';
  }

  bool get _isAndroidClient => !kIsWeb && Platform.isAndroid;

  bool get _studioLightControls =>
      !_isAndroidClient && selectedSection == _WorkspaceSection.studio;

  Map<String, dynamic>? get _cloudUser {
    final user = cloudSession?['user'];
    if (user is Map) return user.cast<String, dynamic>();
    return null;
  }

  bool get _cloudLoggedIn => cloudDeviceToken.isNotEmpty;

  bool get _cloudLicensed =>
      _isAndroidClient ||
      (cloudActivationValid && cloudActivationToken.isNotEmpty);

  bool get _cloudAccountBound {
    if (cloudAccountSignedOut) return false;
    final email = _cloudUser?['email'] as String? ?? '';
    return email.trim().isNotEmpty;
  }

  bool _ensureSoftwareActivated() {
    if (_isAndroidClient) return true;
    if (!_cloudLicensed) {
      showError('请先输入激活码激活软件');
      return false;
    }
    return true;
  }

  bool _ensureCloudAccountReady() {
    if (!_ensureSoftwareActivated()) return false;
    if (!_cloudLoggedIn || !_cloudAccountBound) {
      showError('请先登录云端账号');
      return false;
    }
    return true;
  }

  Map<String, String> _cloudHeaders({
    bool auth = true,
    bool activation = true,
  }) {
    return {
      'Content-Type': 'application/json',
      if (activation && cloudActivationToken.isNotEmpty)
        'X-Device-Token': cloudActivationToken,
      if (auth && cloudDeviceToken.isNotEmpty)
        'Authorization': 'Bearer $cloudDeviceToken',
    };
  }

  Future<File> _cloudAuthFile() async {
    final dir = await getApplicationSupportDirectory();
    await dir.create(recursive: true);
    return File('${dir.path}${Platform.pathSeparator}cloud_auth.json');
  }

  Future<void> _loadCloudAuth() async {
    try {
      final currentFile = await _cloudAuthFile();
      var file = currentFile;
      if (!await file.exists()) {
        final legacyFile = File(
          '${currentFile.parent.parent.path}'
          '${Platform.pathSeparator}oral_video_agent_client'
          '${Platform.pathSeparator}cloud_auth.json',
        );
        if (!await legacyFile.exists()) return;
        file = legacyFile;
      }
      final saved =
          jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      final savedBase = saved['cloud_api_base'] as String? ?? '';
      var savedToken = saved['device_token'] as String? ?? '';
      final hasSeparateActivationToken = saved.containsKey('activation_token');
      var savedActivationToken =
          saved['activation_token'] as String? ?? savedToken;
      final savedEmail = saved['email'] as String? ?? '';
      final savedSignedOut = saved['account_signed_out'] == true;
      if (_isAndroidClient) {
        final secureDeviceToken =
            await _readAndroidSecureValue(_secureDeviceTokenKey);
        final secureActivationToken =
            await _readAndroidSecureValue(_secureActivationTokenKey);
        if ((secureDeviceToken == null || secureDeviceToken.isEmpty) &&
            savedToken.isNotEmpty &&
            !savedSignedOut) {
          await _writeAndroidSecureValue(_secureDeviceTokenKey, savedToken);
        } else {
          savedToken = secureDeviceToken ?? '';
        }
        if ((secureActivationToken == null || secureActivationToken.isEmpty) &&
            savedActivationToken.isNotEmpty) {
          await _writeAndroidSecureValue(
            _secureActivationTokenKey,
            savedActivationToken,
          );
        } else {
          savedActivationToken = secureActivationToken ?? '';
        }
      }
      if (!mounted) return;
      setState(() {
        if (savedBase.isNotEmpty &&
            (!_isAndroidClient || _isSecureCloudBase(savedBase))) {
          cloudApiController.text = savedBase;
        }
        if (savedEmail.isNotEmpty) {
          cloudEmailController.text = savedEmail;
        }
        cloudActivationToken = savedActivationToken;
        cloudDeviceToken =
            (_isAndroidClient || hasSeparateActivationToken) && !savedSignedOut
                ? savedToken
                : '';
        cloudAccountSignedOut = savedSignedOut;
      });
      if (_isAndroidClient) {
        await _saveCloudAuth();
      }
      if (savedActivationToken.isNotEmpty) {
        final activated = await _validateCloudActivation();
        if (!activated) {
          await _clearCloudAuth();
          return;
        }
        await _saveCloudAuth();
      }
      if (cloudDeviceToken.isNotEmpty) {
        await loadCloudMe(silent: true);
      }
    } catch (_) {
      await _clearCloudAuth();
    }
  }

  Future<void> _saveCloudAuth() async {
    final file = await _cloudAuthFile();
    if (_isAndroidClient) {
      if (cloudActivationToken.isEmpty) {
        await _deleteAndroidSecureValue(_secureActivationTokenKey);
      } else {
        await _writeAndroidSecureValue(
          _secureActivationTokenKey,
          cloudActivationToken,
        );
      }
      if (cloudDeviceToken.isEmpty) {
        await _deleteAndroidSecureValue(_secureDeviceTokenKey);
      } else {
        await _writeAndroidSecureValue(
          _secureDeviceTokenKey,
          cloudDeviceToken,
        );
      }
      await file.writeAsString(
        jsonEncode({
          'storage_version': 2,
          'cloud_api_base': _cloudApiBase,
          'email': cloudEmailController.text.trim(),
          'account_signed_out': cloudAccountSignedOut,
        }),
        flush: true,
      );
      return;
    }
    await file.writeAsString(jsonEncode({
      'cloud_api_base': _cloudApiBase,
      'activation_token': cloudActivationToken,
      'device_token': cloudDeviceToken,
      'email': cloudEmailController.text.trim(),
      'account_signed_out': cloudAccountSignedOut,
    }));
  }

  Future<void> _clearCloudAuth() async {
    try {
      if (_isAndroidClient) {
        await _deleteAndroidSecureValue(_secureActivationTokenKey);
        await _deleteAndroidSecureValue(_secureDeviceTokenKey);
      }
      final file = await _cloudAuthFile();
      if (await file.exists()) {
        await file.delete();
      }
    } catch (_) {
      // 清理失败不阻断重新激活流程?    }
    }
    if (!mounted) return;
    setState(() {
      cloudActivationToken = '';
      cloudActivationValid = false;
      cloudDeviceToken = '';
      cloudSession = null;
      cloudWallet = null;
      cloudLedger = const [];
      cloudAccountSignedOut = false;
      cloudAuthMode = 'login';
    });
  }

  Future<void> _clearCloudAccountSession() async {
    if (!mounted) return;
    setState(() {
      cloudDeviceToken = '';
      cloudSession = null;
      cloudWallet = null;
      cloudLedger = const [];
      cloudAccountSignedOut = true;
      cloudAuthMode = 'login';
    });
    await _saveCloudAuth();
  }

  String _deviceFingerprint() {
    final user =
        Platform.environment['USERNAME'] ?? Platform.environment['USER'] ?? '';
    return [
      Platform.operatingSystem,
      Platform.localHostname,
      user,
    ].where((item) => item.trim().isNotEmpty).join(':');
  }

  String _deviceName() {
    if (_isAndroidClient) return 'Android phone';
    final host = Platform.localHostname.trim();
    if (host.isEmpty) return 'Windows client';
    return '${Platform.operatingSystem} $host';
  }

  Map<String, dynamic> _decodeMap(http.Response res) {
    return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
  }

  Future<bool> _validateCloudActivation() async {
    if (cloudActivationToken.isEmpty) return false;
    try {
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/activation'),
        headers: _cloudHeaders(auth: false),
      );
      if (res.statusCode < 200 || res.statusCode >= 300) return false;
      final body = _decodeMap(res);
      final activated = body['activated'] == true;
      if (mounted) setState(() => cloudActivationValid = activated);
      return activated;
    } catch (_) {
      return false;
    }
  }

  Future<void> loadCloudMe({bool silent = false}) async {
    if (!_cloudLoggedIn) {
      if (!silent) showError('请先输入激活码激活软件');
      return;
    }
    try {
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/me'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) return;
      setState(() {
        cloudSession = body;
        cloudWallet = (body['wallet'] as Map?)?.cast<String, dynamic>();
        final user = (body['user'] as Map?)?.cast<String, dynamic>();
        final email = user?['email'] as String? ?? '';
        if (email.isNotEmpty) cloudEmailController.text = email;
        if (!silent) {
          message = '云端账号已刷新';
          messageIsError = false;
        }
      });
      await _saveCloudAuth();
    } catch (e) {
      if (silent) {
        await _clearCloudAccountSession();
      } else {
        showError(e.toString());
      }
    }
  }

  Future<void> loadCloudLedger({bool silent = false}) async {
    if (!_cloudLicensed || !_cloudLoggedIn) return;
    try {
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/credits/ledger'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) return;
      setState(() {
        cloudWallet = (body['wallet'] as Map?)?.cast<String, dynamic>();
        cloudLedger =
            (body['items'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
        if (!silent) {
          message = '点数明细已刷新';
          messageIsError = false;
        }
      });
    } catch (e) {
      if (!silent) showError(e.toString());
    }
  }

  Future<void> loadMobileCloudJobs({bool silent = false}) async {
    if (!_cloudLoggedIn) return;
    try {
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/jobs?limit=50'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) return;
      setState(() {
        mobileCloudJobs =
            (body['items'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
        if (!silent) {
          message = '云端任务已刷新';
          messageIsError = false;
        }
      });
    } catch (e) {
      if (!silent) showError(_friendlyError(e));
    }
  }

  Future<void> sendCloudEmailCode({String purpose = 'register'}) async {
    if (!_ensureSoftwareActivated()) return;
    final email = cloudEmailController.text.trim();
    if (email.isEmpty) {
      showError('请输入邮箱');
      return;
    }
    final mobileFingerprint =
        _isAndroidClient ? await _mobileDeviceFingerprint() : '';
    final endpoint = _isAndroidClient
        ? '/api/mobile/auth/email-code'
        : '/api/client/auth/email-code';
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase$endpoint'),
        headers: _isAndroidClient
            ? _cloudHeaders(auth: false, activation: false)
            : _cloudHeaders(),
        body: jsonEncode({
          'email': email,
          'purpose': purpose,
          if (_isAndroidClient) 'device_fingerprint': mobileFingerprint,
        }),
      );
      if (!_isAndroidClient && res.statusCode == 401) {
        await _clearCloudAuth();
        throw Exception('软件激活状态已失效，请重新输入激活码激活');
      }
      _check(res);
      final body = _decodeMap(res);
      final debugCode = body['debug_code'] as String? ?? '';
      final resendSeconds = (body['resend_seconds'] as num?)?.toInt() ?? 60;
      setState(() {
        if (debugCode.isNotEmpty) {
          cloudEmailCodeController.text = debugCode;
          message = '验证码已发送，已自动填入';
        } else {
          message = '验证码已发送';
        }
        messageIsError = false;
      });
      _startCloudEmailCodeCooldown(resendSeconds);
      await _saveCloudAuth();
    });
  }

  void _startCloudEmailCodeCooldown(int seconds) {
    cloudEmailCodeTimer?.cancel();
    if (!mounted) return;
    setState(() => cloudEmailCodeCooldown = math.max(0, seconds));
    if (cloudEmailCodeCooldown == 0) return;
    cloudEmailCodeTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted || cloudEmailCodeCooldown <= 1) {
        timer.cancel();
        if (mounted) setState(() => cloudEmailCodeCooldown = 0);
        return;
      }
      setState(() => cloudEmailCodeCooldown--);
    });
  }

  Future<bool> loginCloudWithPassword() async {
    if (!_ensureSoftwareActivated()) return false;
    final email = cloudEmailController.text.trim();
    final password = cloudPasswordController.text;
    if (email.isEmpty) {
      showError('请输入邮箱');
      return false;
    }
    if (password.isEmpty) {
      showError('请输入密码');
      return false;
    }
    final mobileFingerprint =
        _isAndroidClient ? await _mobileDeviceFingerprint() : '';
    final endpoint = _isAndroidClient
        ? '/api/mobile/auth/password-login'
        : '/api/client/auth/password-login';
    var succeeded = false;
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase$endpoint'),
        headers: _isAndroidClient
            ? _cloudHeaders(auth: false, activation: false)
            : _cloudHeaders(),
        body: jsonEncode({
          'email': email,
          'password': password,
          'device_name': _deviceName(),
          if (_isAndroidClient) 'device_fingerprint': mobileFingerprint,
        }),
      );
      _check(res);
      final body = _decodeMap(res);
      setState(() {
        cloudAccountSignedOut = false;
        cloudDeviceToken = body['device_token'] as String? ?? cloudDeviceToken;
        cloudSession = body;
        cloudWallet = (body['wallet'] as Map?)?.cast<String, dynamic>();
        cloudEmailCodeController.clear();
        cloudPasswordController.clear();
        cloudPasswordConfirmController.clear();
        message = '云端账号登录成功';
        messageIsError = false;
      });
      await _saveCloudAuth();
      await loadCloudLedger(silent: true);
      if (_isAndroidClient) await loadMobileCloudJobs(silent: true);
      succeeded = true;
    });
    return succeeded;
  }

  Future<bool> registerCloudAccount() async {
    return _completePasswordCodeAuth(
      endpoint: 'register',
      passwordKey: 'password',
      successMessage: '云端账号注册并登录成功',
    );
  }

  Future<bool> resetCloudPassword() async {
    return _completePasswordCodeAuth(
      endpoint: 'password-reset',
      passwordKey: 'new_password',
      successMessage: '密码已重置并登录',
    );
  }

  Future<bool> _completePasswordCodeAuth({
    required String endpoint,
    required String passwordKey,
    required String successMessage,
  }) async {
    if (!_ensureSoftwareActivated()) return false;
    final email = cloudEmailController.text.trim();
    final code = cloudEmailCodeController.text.trim();
    final password = cloudPasswordController.text;
    final confirm = cloudPasswordConfirmController.text;
    if (email.isEmpty) {
      showError('请输入邮箱');
      return false;
    }
    if (code.isEmpty) {
      showError('请输入邮箱验证码');
      return false;
    }
    if (password.length < 8) {
      showError('密码至少需要 8 个字符');
      return false;
    }
    if (password != confirm) {
      showError('两次输入的密码不一致');
      return false;
    }
    final mobileFingerprint =
        _isAndroidClient ? await _mobileDeviceFingerprint() : '';
    final endpointPrefix =
        _isAndroidClient ? '/api/mobile/auth' : '/api/client/auth';
    var succeeded = false;
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase$endpointPrefix/$endpoint'),
        headers: _isAndroidClient
            ? _cloudHeaders(auth: false, activation: false)
            : _cloudHeaders(),
        body: jsonEncode({
          'email': email,
          'code': code,
          passwordKey: password,
          'device_name': _deviceName(),
          if (_isAndroidClient) 'device_fingerprint': mobileFingerprint,
        }),
      );
      if (!_isAndroidClient && res.statusCode == 401) {
        await _clearCloudAuth();
        throw Exception('软件激活状态已失效，请重新输入激活码激活');
      }
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) return;
      setState(() {
        cloudAccountSignedOut = false;
        cloudDeviceToken = body['device_token'] as String? ?? '';
        cloudSession = body;
        cloudWallet = (body['wallet'] as Map?)?.cast<String, dynamic>();
        cloudEmailCodeController.clear();
        cloudPasswordController.clear();
        cloudPasswordConfirmController.clear();
        message = successMessage;
        messageIsError = false;
      });
      await _saveCloudAuth();
      await loadCloudLedger(silent: true);
      if (_isAndroidClient) await loadMobileCloudJobs(silent: true);
      succeeded = true;
    });
    return succeeded;
  }

  Future<void> activateCloudLicense() async {
    await _activateSoftwareFromInput();
  }

  Future<bool> _activateSoftwareFromInput() async {
    final code = cloudActivationCodeController.text.trim();
    if (code.isEmpty) {
      showError('请输入激活码');
      return false;
    }
    var activated = false;
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase/api/client/activate'),
        headers: _cloudHeaders(auth: false, activation: false),
        body: jsonEncode({
          'license_key': code,
          'device_fingerprint': _deviceFingerprint(),
          'device_name': _deviceName(),
        }),
      );
      _check(res);
      final body = _decodeMap(res);
      setState(() {
        cloudActivationToken = body['device_token'] as String? ?? '';
        cloudActivationValid = cloudActivationToken.isNotEmpty;
        cloudDeviceToken = '';
        cloudSession = null;
        cloudWallet = null;
        cloudAccountSignedOut = false;
        cloudActivationCodeController.clear();
        message = '软件已激活，请绑定邮箱账号管理点数';
        messageIsError = false;
      });
      await _saveCloudAuth();
      activated = true;
    });
    return activated;
  }

  Widget _accountModule() {
    if (_cloudAccountBound) return _boundAccountModule();
    return _emailLoginModule();
  }

  Widget _emailLoginModule() {
    return Container(
      constraints: const BoxConstraints(minHeight: 58, maxWidth: 520),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF202438),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: purpleLine.withValues(alpha: 0.85)),
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF368BFF), Color(0xFFE65CD6)],
              ),
              borderRadius: BorderRadius.circular(11),
            ),
            child: const Icon(Icons.lock_person_outlined, color: Colors.white),
          ),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('欢迎回来',
                    style:
                        TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
                SizedBox(height: 2),
                Text('使用邮箱和密码登录云端账号',
                    style: TextStyle(color: Colors.white54, fontSize: 12)),
              ],
            ),
          ),
          OutlinedButton(
            onPressed: loading ? null : () => _showCloudAuthDialog('register'),
            child: const Text('注册'),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            onPressed: loading ? null : () => _showCloudAuthDialog('login'),
            icon: const Icon(Icons.login_rounded, size: 18),
            label: const Text('登录'),
          ),
        ],
      ),
    );
  }

  Future<void> _showCloudAuthDialog(String initialMode) async {
    cloudAuthMode = initialMode;
    message = '';
    messageIsError = false;
    cloudEmailCodeController.clear();
    cloudPasswordController.clear();
    cloudPasswordConfirmController.clear();
    cloudPasswordVisible = false;
    cloudPasswordConfirmVisible = false;
    Timer? dialogTimer;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setModalState) {
          dialogTimer ??= Timer.periodic(const Duration(seconds: 1), (_) {
            if (dialogContext.mounted) setModalState(() {});
          });
          final mode = cloudAuthMode;
          final isLogin = mode == 'login';
          final isRegister = mode == 'register';
          final title = isLogin ? '欢迎回来' : (isRegister ? '创建账号' : '重置密码');
          final subtitle = isLogin
              ? '使用邮箱账号和密码登录'
              : (isRegister ? '验证邮箱并设置首次登录密码' : '验证邮箱后设置新密码');
          return Dialog(
            backgroundColor: Colors.transparent,
            insetPadding: EdgeInsets.symmetric(
              horizontal: _isAndroidClient ? 16 : 40,
              vertical: _isAndroidClient ? 20 : 24,
            ),
            child: Container(
              width: _isAndroidClient ? double.infinity : 500,
              padding: EdgeInsets.fromLTRB(
                _isAndroidClient ? 20 : 30,
                _isAndroidClient ? 16 : 24,
                _isAndroidClient ? 20 : 30,
                _isAndroidClient ? 22 : 28,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFF1D2132),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: purpleLine.withValues(alpha: 0.75)),
                boxShadow: const [
                  BoxShadow(
                      color: Colors.black54,
                      blurRadius: 34,
                      offset: Offset(0, 16)),
                ],
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Align(
                      alignment: Alignment.centerRight,
                      child: IconButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ),
                    Container(
                      width: 62,
                      height: 62,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [Color(0xFF368BFF), Color(0xFFE65CD6)],
                        ),
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: const Icon(Icons.play_arrow_rounded,
                          size: 38, color: Colors.white),
                    ),
                    const SizedBox(height: 16),
                    Text(title,
                        style: const TextStyle(
                            fontSize: 28, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 6),
                    Text(subtitle,
                        style: const TextStyle(
                            color: Colors.white54, fontSize: 14)),
                    if (messageIsError) ...[
                      const SizedBox(height: 12),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color:
                              const Color(0xFFFF7892).withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(9),
                        ),
                        child: Text(
                          message,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Color(0xFFFF9BAD),
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 28),
                    _cloudAuthField(
                      controller: cloudEmailController,
                      label: '邮箱',
                      hint: '请输入邮箱',
                      icon: Icons.mail_outline_rounded,
                    ),
                    const SizedBox(height: 14),
                    _cloudAuthField(
                      controller: cloudPasswordController,
                      label: isLogin ? '密码' : (isRegister ? '设置密码' : '新密码'),
                      hint: '至少 8 个字符',
                      icon: Icons.lock_outline_rounded,
                      obscureText: !cloudPasswordVisible,
                      onToggleVisibility: () => setModalState(
                        () => cloudPasswordVisible = !cloudPasswordVisible,
                      ),
                    ),
                    if (!isLogin) ...[
                      const SizedBox(height: 14),
                      _cloudAuthField(
                        controller: cloudPasswordConfirmController,
                        label: '确认密码',
                        hint: '请再次输入密码',
                        icon: Icons.lock_reset_rounded,
                        obscureText: !cloudPasswordConfirmVisible,
                        onToggleVisibility: () => setModalState(
                          () => cloudPasswordConfirmVisible =
                              !cloudPasswordConfirmVisible,
                        ),
                      ),
                      const SizedBox(height: 14),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Expanded(
                            child: _cloudAuthField(
                              controller: cloudEmailCodeController,
                              label: '邮箱验证码',
                              hint: '请输入验证码',
                              icon: Icons.verified_outlined,
                            ),
                          ),
                          const SizedBox(width: 10),
                          SizedBox(
                            height: 48,
                            child: OutlinedButton(
                              onPressed: loading || cloudEmailCodeCooldown > 0
                                  ? null
                                  : () async {
                                      await sendCloudEmailCode(
                                        purpose: isRegister
                                            ? 'register'
                                            : 'reset_password',
                                      );
                                      if (dialogContext.mounted)
                                        setModalState(() {});
                                    },
                              child: Text(cloudEmailCodeCooldown > 0
                                  ? '${cloudEmailCodeCooldown} 秒'
                                  : '发送验证码'),
                            ),
                          ),
                        ],
                      ),
                    ],
                    if (isLogin)
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton(
                          onPressed: () => setModalState(() {
                            cloudAuthMode = 'reset';
                            cloudEmailCodeController.clear();
                            cloudPasswordController.clear();
                          }),
                          child: const Text('忘记密码？'),
                        ),
                      )
                    else
                      const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: FilledButton.icon(
                        onPressed: loading
                            ? null
                            : () async {
                                final ok = isLogin
                                    ? await loginCloudWithPassword()
                                    : (isRegister
                                        ? await registerCloudAccount()
                                        : await resetCloudPassword());
                                if (ok && dialogContext.mounted) {
                                  Navigator.pop(dialogContext);
                                }
                              },
                        icon: Icon(isLogin
                            ? Icons.login_rounded
                            : Icons.arrow_forward_rounded),
                        label: Text(isLogin
                            ? '登录'
                            : (isRegister ? '注册并登录' : '重置密码并登录')),
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextButton(
                      onPressed: () => setModalState(() {
                        cloudAuthMode = isRegister ? 'login' : 'register';
                        cloudEmailCodeController.clear();
                        cloudPasswordController.clear();
                        cloudPasswordConfirmController.clear();
                      }),
                      child: Text(isRegister ? '已有账号？返回登录' : '还没有账号？立即注册'),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
    dialogTimer?.cancel();
  }

  Widget _cloudAuthField({
    required TextEditingController controller,
    required String label,
    required String hint,
    required IconData icon,
    bool obscureText = false,
    VoidCallback? onToggleVisibility,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontWeight: FontWeight.w800, color: Colors.white70)),
        const SizedBox(height: 7),
        TextField(
          controller: controller,
          obscureText: obscureText,
          decoration: InputDecoration(
            hintText: hint,
            prefixIcon: Icon(icon, color: Colors.white38),
            suffixIcon: onToggleVisibility == null
                ? null
                : IconButton(
                    onPressed: onToggleVisibility,
                    icon: Icon(
                      obscureText
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                      color: Colors.white38,
                    ),
                  ),
            filled: true,
            fillColor: const Color(0xFF151827),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Colors.white12),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Colors.white12),
            ),
          ),
        ),
      ],
    );
  }

  Widget _boundAccountModule() {
    final wallet = cloudWallet ?? const <String, dynamic>{};
    final available = wallet['available_points'] ?? 0;
    final frozen = wallet['frozen_points'] ?? 0;
    return Container(
      constraints: const BoxConstraints(minHeight: 58, maxWidth: 720),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFF202438),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: purpleLine.withValues(alpha: 0.85)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.account_circle, size: 22, color: Color(0xFFD4A4FF)),
          const SizedBox(width: 8),
          Flexible(
            flex: 3,
            child: _headerInfo('账号', _cloudAccountText),
          ),
          const SizedBox(width: 12),
          _headerInfo('可用', '$available 点',
              valueColor: const Color(0xFFB9F8D0)),
          const SizedBox(width: 12),
          _headerInfo('冻结', '$frozen 点'),
          const SizedBox(width: 12),
          Flexible(
            flex: 3,
            child: _headerInfo('点数明细', _latestLedgerText),
          ),
          const SizedBox(width: 8),
          _headerIconButton(Icons.refresh, () async {
            await loadCloudMe(silent: true);
            await loadCloudLedger(silent: true);
          }),
          const SizedBox(width: 8),
          _headerButton('退出登录', logoutCloudAccount),
        ],
      ),
    );
  }

  Widget _headerInfo(String label, String value, {Color? valueColor}) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(color: Colors.white54, fontSize: 11)),
        const SizedBox(height: 2),
        Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            color: valueColor ?? Colors.white,
            fontSize: 13,
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }

  Widget _headerButton(
    String text,
    VoidCallback onPressed, {
    bool primary = false,
    bool enabled = true,
  }) {
    return SizedBox(
      height: 38,
      child: primary
          ? ElevatedButton(
              onPressed: loading || !enabled ? null : onPressed,
              style: ElevatedButton.styleFrom(
                elevation: 0,
                foregroundColor: Colors.white,
                backgroundColor: cyan,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8)),
              ),
              child: Text(text,
                  style: const TextStyle(fontWeight: FontWeight.w900)),
            )
          : OutlinedButton(
              onPressed: loading || !enabled ? null : onPressed,
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: BorderSide(color: purpleLine.withValues(alpha: 0.8)),
                padding: const EdgeInsets.symmetric(horizontal: 10),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8)),
              ),
              child: Text(text,
                  style: const TextStyle(fontWeight: FontWeight.w800)),
            ),
    );
  }

  Widget _headerIconButton(IconData icon, VoidCallback onPressed) {
    return SizedBox(
      width: 36,
      height: 36,
      child: IconButton(
        tooltip: '刷新账号点数',
        onPressed: loading ? null : onPressed,
        icon: Icon(icon, size: 18),
        color: Colors.white,
        style: IconButton.styleFrom(
          backgroundColor: panelBg2,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
    );
  }

  int? _cloudDurationSeconds() {
    final value = int.tryParse(cloudDurationController.text.trim());
    if (value == null || value <= 0) return null;
    return value;
  }

  Future<void> estimateCloudJob() async {
    if (!_ensureCloudAccountReady()) return;
    final duration = _cloudDurationSeconds();
    if (duration == null) {
      showError('请输入云端任务时长');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/estimate'),
        headers: _cloudHeaders(),
        body: jsonEncode({
          'duration_seconds': duration,
          'resolution': '1080p',
        }),
      );
      _check(res);
      final body = _decodeMap(res);
      setState(() {
        cloudEstimate = body;
        cloudWallet = (body['wallet'] as Map?)?.cast<String, dynamic>();
        message = '云端任务已预估';
        messageIsError = false;
      });
    });
  }

  Future<_BootstrapResult> _loadBootstrapFromAvailableApi() async {
    final candidates = _apiBaseCandidates();
    Object? lastError;
    for (final candidate in candidates) {
      try {
        return await _loadBootstrapCandidate(candidate);
      } catch (e) {
        lastError = e;
      }
    }
    if (await _startBundledLocalApiIfAvailable()) {
      for (var attempt = 0; attempt < 40; attempt++) {
        await Future<void>.delayed(const Duration(milliseconds: 500));
        for (final candidate in candidates) {
          try {
            return await _loadBootstrapCandidate(
              candidate,
              timeout: const Duration(seconds: 2),
            );
          } catch (e) {
            lastError = e;
          }
        }
      }
    }
    throw Exception('无法连接本地服务：$lastError');
  }

  Future<_BootstrapResult> _loadBootstrapCandidate(
    String candidate, {
    Duration timeout = const Duration(seconds: 20),
  }) async {
    final res =
        await http.get(Uri.parse('$candidate/api/bootstrap')).timeout(timeout);
    _check(res);
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (_isExpectedBootstrapPayload(body)) {
      return _BootstrapResult(candidate, body);
    }
    throw Exception('$candidate 不是当前口播智能体后端');
  }

  Future<bool> _startBundledLocalApiIfAvailable() async {
    if (!Platform.isWindows || _localApiProcess != null) return false;
    final appDir = File(Platform.resolvedExecutable).parent;
    final candidates = [
      File('${appDir.path}${Platform.pathSeparator}oral_video_agent_api.exe'),
      File('${appDir.path}${Platform.pathSeparator}api'
          '${Platform.pathSeparator}oral_video_agent_api.exe'),
      File('${appDir.path}${Platform.pathSeparator}backend'
          '${Platform.pathSeparator}oral_video_agent_api.exe'),
    ];
    for (final apiExe in candidates) {
      if (!await apiExe.exists()) continue;
      _localApiProcess = await Process.start(
        apiExe.path,
        const ['--host', '127.0.0.1', '--port', '8000'],
        workingDirectory: appDir.path,
        environment: {'ORAL_VIDEO_AGENT_HOME': appDir.path},
      );
      unawaited(_localApiProcess!.stdout.drain<void>());
      unawaited(_localApiProcess!.stderr.drain<void>());
      return true;
    }
    if (kDebugMode) {
      return _startDevelopmentLocalApi(appDir);
    }
    return false;
  }

  Future<bool> _startDevelopmentLocalApi(Directory appDir) async {
    final roots = <Directory>[Directory.current, appDir];
    final visited = <String>{};
    for (final start in roots) {
      var current = start.absolute;
      for (var depth = 0; depth < 10; depth++) {
        if (!visited.add(current.path)) break;
        final apiDir =
            Directory('${current.path}${Platform.pathSeparator}services'
                '${Platform.pathSeparator}api');
        final mainFile = File('${apiDir.path}${Platform.pathSeparator}app'
            '${Platform.pathSeparator}main.py');
        if (await mainFile.exists()) {
          final projectPython = File(
              '${apiDir.path}${Platform.pathSeparator}.venv'
              '${Platform.pathSeparator}Scripts${Platform.pathSeparator}python.exe');
          final rootPython = File(
              '${current.path}${Platform.pathSeparator}.venv'
              '${Platform.pathSeparator}Scripts${Platform.pathSeparator}python.exe');
          final python = await projectPython.exists()
              ? projectPython.path
              : await rootPython.exists()
                  ? rootPython.path
                  : 'python';
          try {
            _localApiProcess = await Process.start(
              python,
              const [
                '-m',
                'uvicorn',
                'app.main:app',
                '--host',
                '127.0.0.1',
                '--port',
                '8000',
              ],
              workingDirectory: apiDir.path,
              environment: {'ORAL_VIDEO_AGENT_HOME': current.path},
            );
            unawaited(_localApiProcess!.stdout.drain<void>());
            unawaited(_localApiProcess!.stderr.drain<void>());
            return true;
          } catch (_) {
            _localApiProcess = null;
            return false;
          }
        }
        final parent = current.parent;
        if (parent.path == current.path) break;
        current = parent;
      }
    }
    return false;
  }

  List<String> _apiBaseCandidates() {
    const preferred = [_configuredApiBase, _fallbackApiBase];
    return [
      for (final base in preferred)
        if (base.isNotEmpty)
          base.endsWith('/') ? base.substring(0, base.length - 1) : base,
    ].toSet().toList();
  }

  bool _isExpectedBootstrapPayload(Map<String, dynamic> body) {
    final humans = body['digital_humans'];
    return body['providers'] is Map &&
        body['voices'] is List &&
        humans is List &&
        body['bgm'] is List &&
        _customDigitalHumansHaveThumbnails(humans);
  }

  bool _customDigitalHumansHaveThumbnails(List<dynamic> humans) {
    for (final item in humans) {
      if (item is! Map) continue;
      final id = item['digital_human_id']?.toString() ?? '';
      final builtIn = item['built_in'] == true;
      if (!builtIn && id.startsWith('custom:')) {
        final thumbnailUrl = item['thumbnail_url']?.toString() ?? '';
        if (thumbnailUrl.isEmpty) return false;
      }
    }
    return true;
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
        localApiOnline = true;
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
      setState(() {
        localApiOnline = false;
        message = e.toString();
        messageIsError = true;
      });
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
    final nickname = _normalizedPublisherNickname(selected?['nickname']);
    if (nickname.isNotEmpty) {
      publisherNicknameController.text = nickname;
    } else {
      publisherNicknameController.text = _publisherNicknamePlaceholder;
    }
  }

  List<Map<String, dynamic>> _dedupePublisherAccounts(
    List<Map<String, dynamic>> accounts,
  ) {
    final kept = <Map<String, dynamic>>[];
    final pendingPlatforms = <String>{};
    for (final account in accounts.reversed) {
      final nickname = _normalizedPublisherNickname(account['nickname']);
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

  void _updateMobile(VoidCallback update) {
    setState(update);
  }

  Future<void> createPublisherAccount() async {
    final rawNickname = publisherNicknameController.text.trim();
    final nickname =
        rawNickname == _publisherNicknamePlaceholder ? '' : rawNickname;
    if (nickname.isNotEmpty) {
      final existing = publisherAccounts.where((account) {
        return account['platform'] == selectedPublishPlatform &&
            (_normalizedPublisherNickname(account['nickname']) == nickname);
      }).toList();
      if (existing.isNotEmpty) {
        setState(() =>
            selectedPublisherAccount = existing.first['account_id'] as String);
        showInfo('该账号已存在，已为你选中');
        return;
      }
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/publisher/accounts'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'platform': selectedPublishPlatform,
          'nickname': nickname,
        }),
      );
      _check(res);
      final account =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      await loadPublisherAccounts();
      setState(() {
        selectedPublisherAccount = account['account_id'] as String;
        message = '账号已添加，请点击登录打开平台登录窗口，登录成功后会自动识别账号名称';
        messageIsError = false;
      });
    });
  }

  Future<void> loginPublisherAccount() async {
    if (selectedPublisherAccount.isEmpty) {
      showError('请先添加或选择发布账号');
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
      showInfo('已请求打开登录窗口，请按平台提示完成扫码或验证');
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
      showError('请先创建视频任务');
      return;
    }
    if (selectedPublisherAccount.isEmpty) {
      showError('请先选择发布账号');
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
    if (generationMode != 'cloud' && _outputVideoPath == null) {
      await loadOutput();
    }
    final publishVideoPath = _outputVideoPath;
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
          'video_path': publishVideoPath ?? '',
          'cover_path': _currentCoverPath ?? '',
        }),
      );
      _check(res);
      await loadPublisherAccounts();
      await _loadTask(taskId);
      showInfo('发布任务已创建，请在下方查看任务状态');
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
      final bodyText = utf8.decode(res.bodyBytes);
      String? detail;
      try {
        final body = jsonDecode(bodyText);
        if (body is Map && body['detail'] != null) {
          detail = body['detail'].toString();
        }
      } catch (_) {
        detail = null;
      }
      if (detail != null && detail.isNotEmpty) {
        throw Exception(detail);
      }
      throw Exception('${res.statusCode}: $bodyText');
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
    if (generatedVoiceKey.isNotEmpty &&
        generatedVoiceKey != _voiceKeyFor(_renderScript)) {
      _invalidateGeneratedVoice();
    }
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
    if (!_ensureSoftwareActivated()) return;
    final shareText = urlController.text.trim();
    if (generationMode == 'cloud' && shareText.isEmpty) {
      await createCloudTranscriptTask();
      return;
    }
    await createLocalLinkTranscriptTask();
  }

  Future<void> createLocalLinkTranscriptTask() async {
    final shareText = urlController.text.trim();
    if (shareText.isEmpty) {
      showError('请先粘贴 Douyin 分享链接，或点击“选择视频”上传本地视频素材');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'douyin_url': shareText}),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        task = body;
        output = null;
        outputRefresh++;
        coverPath = '';
        _invalidateGeneratedVoice();
        publishContentGeneratedKey = '';
        publishTitleController.clear();
        publishBodyController.clear();
        publishTopicsController.clear();
        message = '正在解析 Douyin 分享链接';
        messageIsError = false;
      });
      _syncEditors(body);
      final taskId = body['task_id'] as String;
      await _pollImport(taskId);
    });
  }

  Future<void> createCloudDouyinTranscriptTask() async {
    if (!_ensureCloudAccountReady()) return;
    final shareText = urlController.text.trim();
    if (shareText.isEmpty) {
      showError('请先粘贴抖音分享链接或完整分享口令');
      return;
    }
    await _runBusy(() async {
      setState(() {
        cloudDouyinTranscription = null;
        message = '正在向服务器提交抖音链接';
        messageIsError = false;
      });
      final created = await http
          .post(
            Uri.parse('$_cloudApiBase/api/client/douyin/transcriptions'),
            headers: _cloudHeaders(),
            body: jsonEncode({'share_text': shareText}),
          )
          .timeout(const Duration(seconds: 30));
      _check(created);
      var current = _decodeMap(created);
      final transcriptionId =
          current['transcription_id']?.toString().trim() ?? '';
      if (transcriptionId.isEmpty) {
        throw Exception('服务器未返回文案提取任务编号');
      }

      for (var attempt = 0; attempt < 400; attempt++) {
        if (!mounted) return;
        final progressMessage =
            current['progress_message']?.toString().trim() ?? '';
        setState(() {
          cloudDouyinTranscription = current;
          message =
              progressMessage.isNotEmpty ? progressMessage : '服务器正在处理抖音视频';
          messageIsError = false;
        });
        final status = current['status']?.toString() ?? '';
        if (status == 'completed') {
          final transcript = current['transcript']?.toString().trim() ?? '';
          if (transcript.isEmpty) {
            throw Exception('服务器没有返回识别出的口播文案');
          }
          setState(() {
            originalScriptController.text = transcript;
            task = {
              'task_id': 'douyin-$transcriptionId',
              'status': 'transcribed',
              'original_script': transcript,
              'rewritten_script': rewrittenScriptController.text.trim(),
              'progress_steps': const [],
            };
            output = null;
            outputRefresh++;
            coverPath = '';
            _invalidateGeneratedVoice();
            message = '服务器已完成抖音视频下载和口播文案提取';
            messageIsError = false;
          });
          return;
        }
        if (status == 'failed') {
          final error = current['error_message']?.toString().trim() ?? '';
          throw Exception(error.isEmpty ? '抖音文案提取失败' : error);
        }

        await Future<void>.delayed(const Duration(seconds: 3));
        final polled = await http
            .get(
              Uri.parse(
                '$_cloudApiBase/api/client/douyin/transcriptions/$transcriptionId',
              ),
              headers: _cloudHeaders(),
            )
            .timeout(const Duration(seconds: 30));
        _check(polled);
        current = _decodeMap(polled);
      }
      throw Exception('服务器处理时间过长，请稍后重试');
    });
  }

  Future<void> createCloudTranscriptTask() async {
    if (!_ensureCloudAccountReady()) return;
    if (cloudSourceVideoPath.isEmpty) {
      showError('请先粘贴 Douyin 分享链接，或点击“选择视频”上传本地视频素材');
      return;
    }
    final sourceFile = File(cloudSourceVideoPath);
    if (!await sourceFile.exists()) {
      showError('选择的视频文件不存在');
      return;
    }
    setState(() {
      loading = true;
      message = '正在提交云端文案提取任务';
      messageIsError = false;
      cloudJob = null;
    });
    try {
      final result = await _runCloudPreprocess(
        payload: {
          'task_type': 'preprocess',
          'operation': 'extract',
          'douyin_url': urlController.text.trim(),
        },
        sourceFile: sourceFile,
        sourceFileName: cloudSourceVideoName.isNotEmpty
            ? cloudSourceVideoName
            : _fileNameFromPath(cloudSourceVideoPath),
      );
      final originalScript = result['original_script']?.toString().trim() ?? '';
      if (originalScript.isEmpty) {
        throw Exception('云端未返回识别文案');
      }
      if (!mounted) return;
      setState(() {
        originalScriptController.text = originalScript;
        task = {
          'task_id':
              'cloud-${cloudJob?['job_id'] ?? DateTime.now().millisecondsSinceEpoch}',
          'status': 'transcribed',
          'original_script': originalScript,
          'rewritten_script': rewrittenScriptController.text.trim(),
          'progress_steps': const [],
        };
        output = null;
        outputRefresh++;
        coverPath = '';
        _invalidateGeneratedVoice();
        message = '云端文案提取完成';
        messageIsError = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        message = e.toString();
        messageIsError = true;
      });
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> rewriteCloud(String source) async {
    if (!_ensureCloudAccountReady()) return;
    setState(() {
      loading = true;
      message = '正在提交云端仿写任务';
      messageIsError = false;
      cloudJob = null;
    });
    try {
      final res = await http
          .post(
            Uri.parse('$_cloudApiBase/api/client/rewrite'),
            headers: _cloudHeaders(),
            body: jsonEncode({
              'source_script': source,
              'style': selectedStyle,
              'max_chars': 300,
              'product_info': productController.text.trim(),
              'target_audience': audienceController.text.trim(),
            }),
          )
          .timeout(const Duration(seconds: 45));
      _check(res);
      final result = _decodeMap(res);
      final rewrittenScript =
          result['rewritten_script']?.toString().trim() ?? '';
      if (rewrittenScript.isEmpty) {
        throw Exception('云端未返回仿写文案');
      }
      if (!mounted) return;
      setState(() {
        rewrittenScriptController.text = rewrittenScript;
        task = {
          ...?task,
          'status': 'rewritten',
          'original_script': source,
          'rewritten_script': rewrittenScript,
          'progress_steps': task?['progress_steps'] ?? const [],
        };
        message = '云端仿写完成';
        messageIsError = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        message = e.toString();
        messageIsError = true;
      });
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> uploadSourceVideo() async {
    if (!_ensureSoftwareActivated()) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4', 'mov', 'mkv', 'webm'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    if (generationMode == 'cloud') {
      final file = File(path);
      if (!await file.exists()) {
        showError('选择的视频文件不存在');
        return;
      }
      setState(() {
        cloudSourceVideoPath = path;
        cloudSourceVideoName =
            picked?.files.single.name ?? _fileNameFromPath(path);
        cloudJob = null;
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
        outputRefresh++;
        message = '已选择云端素材：$cloudSourceVideoName';
        messageIsError = false;
      });
      return;
    }
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
    final deadline = DateTime.now().add(const Duration(minutes: 20));
    while (DateTime.now().isBefore(deadline)) {
      await Future.delayed(const Duration(seconds: 3));
      final res = await http.get(Uri.parse('$apiBase/api/tasks/$taskId'));
      if (res.statusCode < 200 || res.statusCode >= 300) return;
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final progressMessage = _importProgressMessage(body);
      setState(() {
        task = body;
        if (progressMessage.isNotEmpty) {
          message = progressMessage;
          messageIsError = false;
        }
      });
      _syncEditors(body);
      final status = body['status'] as String? ?? '';
      if (status == 'failed') {
        setState(() => message = body['error_message'] as String? ?? '导入失败');
        return;
      }
      if ((body['original_script'] as String? ?? '').isNotEmpty ||
          status == 'transcribed' ||
          status == 'completed') {
        setState(() {
          message = '视频文案提取完成';
          messageIsError = false;
        });
        return;
      }
    }
    if (!mounted) return;
    setState(() {
      message = '视频还在后台处理，长视频可能需要更久；稍后点击刷新或重新打开任务即可查看结果';
      messageIsError = false;
    });
  }

  String _importProgressMessage(Map<String, dynamic> body) {
    if ((body['original_script'] as String? ?? '').trim().isNotEmpty) {
      return '视频文案提取完成';
    }
    final active = _activeProgressStep(body);
    final key = active?['key'] as String? ?? '';
    return switch (key) {
      'resolve_link' => '正在解析 Douyin 分享链接',
      'download_video' => '正在下载源视频，长视频会稍慢',
      'transcribe' => '正在识别视频文案，5分钟以上视频可能需要几分钟',
      'extract' => '正在提取视频文案',
      _ => '',
    };
  }

  Future<void> rewrite() async {
    if (!_ensureSoftwareActivated()) return;
    final source = originalScriptController.text.trim();
    if (source.isEmpty) {
      setState(() => message = '请先提取或填写原始文案');
      return;
    }
    if (generationMode == 'cloud') {
      await rewriteCloud(source);
      return;
    }
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
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
    if (!_ensureSoftwareActivated()) return;
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

  Future<void> generateCover() async {
    if (!_ensureSoftwareActivated()) return;
    final taskId = task?['task_id'] as String?;
    final script = _renderScript;
    if (taskId == null && script.isEmpty) {
      showError('请先生成文案后再生成封面');
      return;
    }
    await _runBusy(() async {
      if (taskId != null && !taskId.startsWith('cloud-')) {
        final res =
            await http.post(Uri.parse('$apiBase/api/tasks/$taskId/cover'));
        _check(res);
        final body =
            jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
        setState(() {
          task = body;
          coverPath = body['cover_path'] as String? ?? coverPath;
          outputRefresh++;
          message = '封面已生成';
          messageIsError = false;
        });
        return;
      }
      final res = await http.post(
        Uri.parse('$apiBase/api/covers/generate'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'title':
              (task?['title'] as String? ?? publishTitleController.text).trim(),
          'script': script,
          'background_path': _outputVideoPath ?? '',
        }),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        coverPath = body['cover_path'] as String? ?? '';
        outputRefresh++;
        message = '封面已生成';
        messageIsError = false;
      });
    });
  }

  Future<void> uploadCover() async {
    if (!_ensureSoftwareActivated()) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['png', 'jpg', 'jpeg', 'webp'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    final taskId = task?['task_id'] as String?;
    if (taskId == null || taskId.startsWith('cloud-')) {
      setState(() {
        coverPath = path;
        outputRefresh++;
        message = '已选择自定义封面';
        messageIsError = false;
      });
      return;
    }
    await _runBusy(() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase/api/tasks/$taskId/cover/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        task = body;
        coverPath = body['cover_path'] as String? ?? path;
        outputRefresh++;
        message = '已上传自定义封面';
        messageIsError = false;
      });
    });
  }

  Future<void> cloneVoice() async {
    if (!_ensureSoftwareActivated()) return;
    var taskId = task?['task_id'] as String?;
    if (_isAndroidClient && taskId == null && _renderScript.isNotEmpty) {
      taskId = 'mobile-${DateTime.now().millisecondsSinceEpoch}';
      setState(() {
        task = {
          'task_id': taskId,
          'status': 'rewritten',
          'original_script': originalScriptController.text.trim(),
          'rewritten_script': rewrittenScriptController.text.trim(),
          'progress_steps': const [],
        };
      });
    }
    if (taskId == null) return;
    final script = _renderScript;
    if (script.isEmpty) {
      showError('请先生成或填写文案');
      return;
    }
    if (selectedVoice.isEmpty) {
      showError('请先选择或上传声音');
      return;
    }
    if (generationMode == 'cloud') {
      await cloneVoiceCloud(taskId, script);
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
      setState(() {
        task = body;
        generatedVoiceKey = _voiceKeyFor(script);
      });
    });
  }

  Future<void> cloneVoiceCloud(String taskId, String script) async {
    if (!_ensureCloudAccountReady()) return;
    setState(() {
      loading = true;
      cloudVoiceCancelRequested = false;
    });
    try {
      final existingJobId = cloudVoiceJobId.trim();
      if (existingJobId.isNotEmpty &&
          await _resumeCloudVoiceJob(existingJobId, script)) {
        return;
      }
      setState(() {
        message = '正在准备云端克隆声音素材';
        messageIsError = false;
      });
      final referencePath = _isAndroidClient
          ? mobileVoiceReferencePath
          : await _downloadPreviewToTempFile(
              _selectedVoicePreviewUrl,
              'voice_reference',
            );
      if (referencePath.isEmpty) {
        throw Exception('请先选择声音参考文件');
      }
      final referenceFile = File(referencePath);
      if (!await referenceFile.exists()) {
        throw Exception('声音参考文件下载失败，请重新选择或上传声音');
      }
      final fileName = _fileNameFromPath(referencePath);
      final uploadSpecs = [
        {
          'kind': 'voice_reference',
          'file_name': fileName,
          'content_type': _contentTypeForPath(fileName),
          'file_size_bytes': await referenceFile.length(),
        }
      ];
      final payload = {
        ..._renderPayload(script),
        'task_type': 'preprocess',
        'operation': 'voice',
        'source_script': script,
        'client_task_id': taskId,
      };
      final sessionRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/preprocess/upload-session'),
        headers: _cloudHeaders(),
        body: jsonEncode({
          'assets': uploadSpecs,
          'payload': payload,
        }),
      );
      _check(sessionRes);
      final uploadJob = _decodeMap(sessionRes);
      final jobId = uploadJob['job_id'] as String;
      if (!mounted) return;
      setState(() {
        cloudJob = uploadJob;
        cloudVoiceJobId = jobId;
      });
      final assets = (uploadJob['assets'] as List?) ?? const [];
      if (assets.length != 1 || assets.first is! Map) {
        throw Exception('云端没有返回声音素材上传链接');
      }
      final asset = (assets.first as Map).cast<String, dynamic>();
      final upload = (asset['upload'] as Map).cast<String, dynamic>();
      setState(() {
        message = '正在上传参考声音到云端';
        messageIsError = false;
      });
      await _uploadFileToPresignedUrl(upload, referenceFile);
      final uploadedRes = await http.post(
        Uri.parse(
          '$_cloudApiBase/api/client/jobs/$jobId/assets/${asset['asset_id']}/uploaded',
        ),
        headers: _cloudHeaders(),
        body: jsonEncode({'file_size_bytes': await referenceFile.length()}),
      );
      _check(uploadedRes);
      final submitRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/preprocess/jobs/$jobId/submit'),
        headers: _cloudHeaders(),
        body: jsonEncode({'payload': payload}),
      );
      _check(submitRes);
      final submitted = _decodeMap(submitRes);
      if (mounted) {
        setState(() {
          cloudJob = submitted;
          message = '云端声音克隆任务已提交';
          messageIsError = false;
        });
      }
      await _finishCloudVoiceJob(jobId, script);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        if (cloudVoiceCancelRequested || e.toString().contains('已取消')) {
          message = '声音克隆任务已停止，可以重新提交';
          messageIsError = false;
        } else {
          message = _friendlyError(e);
          messageIsError = true;
        }
      });
    } finally {
      if (mounted) {
        setState(() {
          loading = false;
          cloudVoiceCancelRequested = false;
        });
      }
    }
  }

  Future<void> stopCloudVoiceJob() async {
    final jobId = cloudVoiceJobId.trim();
    if (jobId.isEmpty) return;
    setState(() => cloudVoiceCancelRequested = true);
    try {
      final res = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/cancel'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) return;
      setState(() {
        cloudJob = body;
        cloudVoiceJobId = '';
        cloudVoiceAudioPath = '';
        generatedVoiceKey = '';
        loading = false;
        message = '声音克隆任务已停止，可以重新提交';
        messageIsError = false;
      });
      await loadCloudMe(silent: true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        cloudVoiceCancelRequested = false;
        message = _friendlyError(e);
        messageIsError = true;
      });
    }
  }

  Future<void> loadTaskHistory({bool silent = false}) async {
    if (!mounted) return;
    setState(() => loadingTaskHistory = true);
    try {
      final res = await http.get(Uri.parse('$apiBase/api/tasks'));
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final items =
          (body['items'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
      if (!mounted) return;
      setState(() {
        taskHistory = items;
        final availableIds = items
            .map((item) => item['task_id']?.toString() ?? '')
            .where((id) => id.isNotEmpty)
            .toSet();
        selectedTaskIds.removeWhere((id) => !availableIds.contains(id));
        localApiOnline = true;
      });
    } catch (e) {
      if (mounted) {
        setState(() => localApiOnline = false);
        if (!silent) showError(_friendlyError(e));
      }
    } finally {
      if (mounted) setState(() => loadingTaskHistory = false);
    }
  }

  Future<void> _openTaskFromHistory(String taskId) async {
    await _runBusy(() async {
      await _loadTask(taskId);
      output = null;
      cloudOutputUrl = '';
      cloudOutputLocalPath = '';
      try {
        await loadOutput();
      } catch (_) {
        // A task can be opened before its output exists.
      }
      if (!mounted) return;
      setState(() {
        selectedSection = _WorkspaceSection.studio;
        message = '已打开任务，可以继续编辑和生成';
        messageIsError = false;
      });
    });
  }

  Future<void> _deleteTaskFromHistory(Map<String, dynamic> item) async {
    final taskId = item['task_id']?.toString() ?? '';
    if (taskId.isEmpty) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删除任务'),
        content: Text('确定删除“${item['title'] ?? '未命名任务'}”及其本地生成文件吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _runBusy(() async {
      final res = await http.delete(Uri.parse('$apiBase/api/tasks/$taskId'));
      _check(res);
      if (task?['task_id'] == taskId) {
        task = null;
        output = null;
        originalScriptController.clear();
        rewrittenScriptController.clear();
      }
      await loadTaskHistory(silent: true);
      showInfo('任务已删除');
    });
  }

  Future<void> logoutCloudAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('退出云端账号'),
        content: Text(_isAndroidClient
            ? '退出后可使用邮箱和密码重新登录。'
            : '退出后不会影响软件激活状态，可重新选择登录或注册。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('退出登录'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      cloudAccountSignedOut = true;
      cloudAuthMode = 'login';
      cloudDeviceToken = '';
      cloudSession = null;
      cloudWallet = null;
      cloudLedger = const [];
      cloudEmailController.clear();
      cloudEmailCodeController.clear();
      message = '已退出云端账号，请选择登录或注册';
      messageIsError = false;
    });
    await _saveCloudAuth();
  }

  Future<void> _deleteSelectedTasks() async {
    if (selectedTaskIds.isEmpty || batchDeletingTasks) return;
    final ids = selectedTaskIds.toList(growable: false);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('批量删除任务'),
        content: Text('确定删除已选中的 ${ids.length} 个任务及其本地生成文件吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.delete_outline_rounded),
            label: const Text('批量删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() {
      batchDeletingTasks = true;
      message = '正在批量删除 ${ids.length} 个任务...';
      messageIsError = false;
    });
    var deleted = 0;
    final failedIds = <String>[];
    for (final taskId in ids) {
      try {
        final res = await http.delete(Uri.parse('$apiBase/api/tasks/$taskId'));
        _check(res);
        deleted++;
        if (task?['task_id'] == taskId) {
          task = null;
          output = null;
          originalScriptController.clear();
          rewrittenScriptController.clear();
        }
      } catch (_) {
        failedIds.add(taskId);
      }
    }
    if (!mounted) return;
    setState(() {
      selectedTaskIds.removeAll(ids.where((id) => !failedIds.contains(id)));
      batchDeletingTasks = false;
    });
    await loadTaskHistory(silent: true);
    if (!mounted) return;
    setState(() {
      message = failedIds.isEmpty
          ? '已批量删除 $deleted 个任务'
          : '已删除 $deleted 个任务，${failedIds.length} 个任务删除失败';
      messageIsError = failedIds.isNotEmpty;
    });
  }

  Future<bool> _resumeCloudVoiceJob(String jobId, String script) async {
    final res = await http.get(
      Uri.parse('$_cloudApiBase/api/client/jobs/$jobId'),
      headers: _cloudHeaders(),
    );
    if (res.statusCode == 404) {
      if (mounted) setState(() => cloudVoiceJobId = '');
      return false;
    }
    _check(res);
    final job = _decodeMap(res);
    final payload = (job['payload'] as Map?)?.cast<String, dynamic>();
    final operation = payload?['operation']?.toString() ?? '';
    final status = job['status']?.toString() ?? '';
    if ((operation.isNotEmpty && operation != 'voice') ||
        !{'queued', 'running', 'completed'}.contains(status)) {
      if (mounted) setState(() => cloudVoiceJobId = '');
      return false;
    }
    if (!mounted) return true;
    setState(() {
      cloudJob = job;
      message = status == 'completed' ? '正在下载已完成的克隆声音' : _cloudJobMessage(job);
      messageIsError = false;
    });
    await _finishCloudVoiceJob(jobId, script);
    return true;
  }

  Future<void> _finishCloudVoiceJob(String jobId, String script) async {
    await _waitCloudPreprocessResult(
      jobId,
      timeout: const Duration(hours: 4),
    );
    final localPath = await _downloadCloudJobOutputToLocal(
      jobId,
      fallbackFileName: 'voice.wav',
    );
    try {
      await confirmCloudDownload(silent: true);
    } catch (_) {
      // The local WAV is already saved; scheduled cleanup still protects cloud storage.
    }
    if (!mounted) return;
    setState(() {
      cloudVoiceAudioPath = localPath;
      generatedVoiceKey = _voiceKeyFor(script);
      outputRefresh++;
      message = '声音已克隆，可以播放声音或生成成品视频';
      messageIsError = false;
    });
  }

  Future<void> playVoice() async {
    if (selectedVoice.isEmpty) {
      showError('请先选择声音');
      return;
    }
    final voiceUrl = _generatedVoiceUrl;
    if (voiceUrl == null) {
      showError('请先点击“克隆声音”生成后再播放声音');
      return;
    }
    try {
      await _stopOriginalAudioPreview();
      if (_isPlayingVoice) {
        await _stopVoicePreview();
        showInfo('已停止播放声音');
        return;
      }
      await _stopVoicePreview();
      _voicePlayer = Player();
      setState(() {
        _isPlayingVoice = true;
        _isPlayingOriginalAudio = false;
      });
      final localPath = _isLocalFilePath(voiceUrl)
          ? voiceUrl
          : await _downloadPreviewToTempFile(voiceUrl, 'voice');
      await _voicePlayer!.open(Media(_playableMediaSource(localPath)));
      await _voicePlayer!.setVolume(_voicePreviewMediaVolume);
      await _voicePlayer!.play();
      await _voicePlayer!.setVolume(_voicePreviewMediaVolume);
      showInfo('正在播放声音');
      _voicePlayer!.stream.completed.listen((completed) {
        if (completed && mounted) setState(() => _isPlayingVoice = false);
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

  Future<void> playOriginalAudio() async {
    if (selectedVoice.isEmpty) {
      showError('请先选择声音');
      return;
    }
    final sourceUrl = _selectedVoicePreviewUrl;
    try {
      await _stopVoicePreview();
      if (_isPlayingOriginalAudio) {
        await _stopOriginalAudioPreview();
        showInfo('已停止播放原音');
        return;
      }
      await _stopOriginalAudioPreview();
      _originalAudioPlayer = Player();
      setState(() {
        _isPlayingOriginalAudio = true;
        _isPlayingVoice = false;
      });
      final localPath =
          await _downloadPreviewToTempFile(sourceUrl, 'original_voice');
      await _originalAudioPlayer!.open(Media(_playableMediaSource(localPath)));
      await _originalAudioPlayer!.setVolume(_voicePreviewMediaVolume);
      await _originalAudioPlayer!.play();
      await _originalAudioPlayer!.setVolume(_voicePreviewMediaVolume);
      showInfo('正在播放原音');
      _originalAudioPlayer!.stream.completed.listen((completed) {
        if (completed && mounted) {
          setState(() => _isPlayingOriginalAudio = false);
        }
      });
    } catch (e) {
      setState(() {
        message = '原音播放失败: ${e.toString()}';
        _isPlayingOriginalAudio = false;
      });
      _originalAudioPlayer?.dispose();
      _originalAudioPlayer = null;
    }
  }

  Future<void> previewVoiceReference(String voiceId) async {
    final switchingVoice = selectedVoice != voiceId;
    if (switchingVoice && _isPlayingOriginalAudio) {
      await _stopOriginalAudioPreview();
    }
    if (!mounted) return;
    setState(() {
      selectedVoice = voiceId;
      if (switchingVoice) _invalidateGeneratedVoice();
    });
    await playOriginalAudio();
  }

  Future<String> _downloadPreviewToTempFile(
    String sourceUrl,
    String prefix, {
    String? preferredFileName,
  }) async {
    final res = await http.get(Uri.parse(sourceUrl));
    _check(res);
    final dir = await getTemporaryDirectory();
    final ext = _extensionForResponse(res, sourceUrl, preferredFileName);
    final hash = sourceUrl.codeUnits
        .fold<int>(0, (value, code) => (value * 31 + code) & 0x7FFFFFFF)
        .toRadixString(16);
    final path = '${dir.path}${Platform.pathSeparator}${prefix}_$hash$ext';
    final file = File(path);
    await file.writeAsBytes(res.bodyBytes, flush: true);
    return file.path;
  }

  String _extensionForResponse(
    http.Response res,
    String sourceUrl,
    String? preferredFileName,
  ) {
    final preferred = (preferredFileName ?? '').toLowerCase();
    for (final ext in const [
      '.wav',
      '.mp3',
      '.m4a',
      '.aac',
      '.flac',
      '.png',
      '.jpg',
      '.jpeg',
      '.webp',
      '.mp4',
      '.mov',
      '.mkv',
      '.webm',
    ]) {
      if (preferred.endsWith(ext)) return ext;
    }
    final contentType = (res.headers['content-type'] ?? '').toLowerCase();
    if (contentType.contains('png')) return '.png';
    if (contentType.contains('jpeg') || contentType.contains('jpg'))
      return '.jpg';
    if (contentType.contains('webp')) return '.webp';
    if (contentType.startsWith('video/mp4')) return '.mp4';
    if (contentType.contains('quicktime')) return '.mov';
    return _audioExtensionForResponse(res, sourceUrl);
  }

  String _audioExtensionForResponse(http.Response res, String sourceUrl) {
    final contentType = (res.headers['content-type'] ?? '').toLowerCase();
    if (contentType.contains('mpeg')) return '.mp3';
    if (contentType.contains('mp4') || contentType.contains('m4a')) {
      return '.m4a';
    }
    if (contentType.contains('aac')) return '.aac';
    if (contentType.contains('flac')) return '.flac';
    if (contentType.contains('wav') || contentType.contains('wave')) {
      return '.wav';
    }
    final path = Uri.tryParse(sourceUrl)?.path.toLowerCase() ?? '';
    for (final ext in const ['.wav', '.mp3', '.m4a', '.aac', '.flac']) {
      if (path.endsWith(ext)) return ext;
    }
    return '.audio';
  }

  String _playableMediaSource(String source) {
    if (source.startsWith('http://') ||
        source.startsWith('https://') ||
        source.startsWith('file://')) {
      return source;
    }
    if (source.contains(RegExp(r'^[A-Za-z]:[\\/]')) ||
        source.startsWith(r'\\')) {
      return Uri.file(source).toString();
    }
    return source;
  }

  bool _isLocalFilePath(String source) {
    if (source.startsWith('file://')) return true;
    if (source.startsWith('http://') || source.startsWith('https://')) {
      return false;
    }
    return source.contains(RegExp(r'^[A-Za-z]:[\\/]')) ||
        source.startsWith(r'\\') ||
        File(source).existsSync();
  }

  Future<void> _stopVoicePreview() async {
    if (_voicePlayer != null) {
      await _voicePlayer?.stop();
      _voicePlayer?.dispose();
      _voicePlayer = null;
    }
    if (mounted && _isPlayingVoice) {
      setState(() => _isPlayingVoice = false);
    }
  }

  Future<void> _stopOriginalAudioPreview() async {
    if (_originalAudioPlayer != null) {
      await _originalAudioPlayer?.stop();
      _originalAudioPlayer?.dispose();
      _originalAudioPlayer = null;
    }
    if (mounted && _isPlayingOriginalAudio) {
      setState(() => _isPlayingOriginalAudio = false);
    }
  }

  Future<void> playBgm() async {
    if (selectedBgm == 'none') {
      showError('请先选择背景音乐');
      return;
    }
    final bgmUrl = _selectedBgmUrl;
    try {
      if (_isPlayingBgm) {
        await _stopBgmPreview();
        showInfo('已停止播放BGM');
        return;
      }
      await _stopBgmPreview();
      _bgmPlayer = Player();
      setState(() => _isPlayingBgm = true);
      final localPath = await _downloadPreviewToTempFile(bgmUrl, 'bgm');
      await _bgmPlayer!.setVolume(_bgmPreviewVolume);
      await _bgmPlayer!.open(Media(_playableMediaSource(localPath)));
      await _bgmPlayer!.setVolume(_bgmPreviewVolume);
      await _bgmPlayer!.play();
      showInfo('正在播放BGM');
      _bgmPlayer!.stream.completed.listen((completed) {
        if (completed && mounted) setState(() => _isPlayingBgm = false);
      });
    } catch (e) {
      setState(() {
        message = '播放BGM失败: ${e.toString()}';
        _isPlayingBgm = false;
      });
      _bgmPlayer?.dispose();
      _bgmPlayer = null;
    }
  }

  Future<void> _stopBgmPreview() async {
    if (_bgmPlayer != null) {
      await _bgmPlayer?.stop();
      _bgmPlayer?.dispose();
      _bgmPlayer = null;
    }
    if (mounted && _isPlayingBgm) {
      setState(() => _isPlayingBgm = false);
    }
  }

  void _updateBgmVolume(double value) {
    setState(() => bgmVolume = value);
    final player = _bgmPlayer;
    if (player != null) {
      unawaited(player.setVolume(_bgmPreviewVolume));
    }
  }

  void _updateVoicePreviewVolume(double value) {
    setState(() => voicePreviewVolume = value);
    final volume = _voicePreviewMediaVolume;
    final voicePlayer = _voicePlayer;
    final originalPlayer = _originalAudioPlayer;
    if (voicePlayer != null) {
      unawaited(voicePlayer.setVolume(volume));
    }
    if (originalPlayer != null) {
      unawaited(originalPlayer.setVolume(volume));
    }
  }

  double get _voicePreviewMediaVolume {
    return (voicePreviewVolume * 100).clamp(0, 100).toDouble();
  }

  double get _bgmPreviewVolume {
    return (bgmVolume * 100).clamp(0, 100).toDouble();
  }

  Future<void> uploadDigitalHuman() async {
    if (!_ensureSoftwareActivated()) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4', 'mov', 'mkv', 'webm'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    if (_isAndroidClient) {
      setState(() {
        mobileDigitalHumanPath = path;
        mobileDigitalHumanName =
            picked?.files.single.name ?? _fileNameFromPath(path);
        selectedDigitalHuman = 'mobile:reference';
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
        outputRefresh++;
        message = '已选择数字人形象视频';
        messageIsError = false;
      });
      return;
    }
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
      setState(() {
        selectedDigitalHuman = digitalHumanId;
        mouthAtlasDiagnosis = null;
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
        outputRefresh++;
        message = '数字人形象已上传并选中';
        messageIsError = false;
      });
    });
  }

  Future<void> deleteDigitalHuman() async {
    if (!_ensureSoftwareActivated()) return;
    final digitalHumanId = selectedDigitalHuman;
    if (digitalHumanId.isEmpty) {
      showError('请先选择要删除的数字人');
      return;
    }
    if (!digitalHumanId.startsWith('custom:')) {
      showError('只能删除你上传的数字人');
      return;
    }
    final assetId = digitalHumanId.substring('custom:'.length);
    if (assetId.isEmpty) {
      showError('数字人素材 ID 无效');
      return;
    }
    await _runBusy(() async {
      final uri =
          Uri.parse('$apiBase/api/assets/${Uri.encodeComponent(assetId)}');
      final res = await http.delete(uri);
      _check(res);
      if (!mounted) return;
      setState(() {
        selectedDigitalHuman = '';
        mouthAtlasDiagnosis = null;
        digitalHumans = digitalHumans
            .where((item) => item['digital_human_id'] != digitalHumanId)
            .toList();
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
        outputRefresh++;
      });
      await loadBootstrap();
      if (!mounted) return;
      setState(() {
        selectedDigitalHuman = '';
        mouthAtlasDiagnosis = null;
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
        outputRefresh++;
      });
      showInfo('已删除数字人');
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
    if (!_ensureSoftwareActivated()) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['wav', 'mp3', 'm4a', 'aac'],
    );
    final path = picked?.files.single.path;
    if (path == null) return;
    if (_isAndroidClient) {
      setState(() {
        mobileVoiceReferencePath = path;
        mobileVoiceReferenceName =
            picked?.files.single.name ?? _fileNameFromPath(path);
        selectedVoice = 'mobile:reference';
        _invalidateGeneratedVoice();
        message = '已选择声音参考文件';
        messageIsError = false;
      });
      return;
    }
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
      setState(() {
        selectedVoice = item['voice_id'] as String;
        _invalidateGeneratedVoice();
      });
    });
  }

  Future<void> uploadBgm() async {
    if (!_ensureSoftwareActivated()) return;
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

  Future<void> uploadPipAsset() async {
    if (!_ensureSoftwareActivated()) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: [
        'png',
        'jpg',
        'jpeg',
        'webp',
        'mp4',
        'mov',
        'mkv',
        'webm'
      ],
    );
    final file = picked?.files.single;
    final path = file?.path;
    if (path == null || file == null) return;
    await _runBusy(() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase/api/pip/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final asset = body['asset'] as Map<String, dynamic>;
      setState(() {
        pipAssetId = asset['asset_id'] as String;
        pipAssetName = asset['filename'] as String? ?? file.name;
        pipAssetPath = path;
        pipEnabled = true;
        message = '画中画素材已上传';
        messageIsError = false;
      });
    });
  }

  Future<void> generateSubtitles() async {
    if (!_ensureSoftwareActivated()) return;
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final script = _renderScript;
    if (script.isEmpty) {
      setState(() => message = '请先生成或填写文案');
      return;
    }
    await _runBusy(() async {
      final res = await http.post(
        Uri.parse('$apiBase/api/tasks/$taskId/subtitles'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(_renderPayload(script)),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      setState(() {
        task = body;
        message = '字幕已生成';
        messageIsError = false;
      });
      await refreshSubtitlePreview(silent: true);
    });
  }

  Future<void> refreshSubtitlePreview({bool silent = false}) async {
    final script = _renderScript;
    if (script.isEmpty) {
      if (!silent) setState(() => message = '请先生成或填写文案');
      return;
    }
    try {
      final res = await http.post(
        Uri.parse('$apiBase/api/subtitles/preview'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'script': script,
          'style': _subtitleStylePayload(),
        }),
      );
      _check(res);
      final body =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      final lines =
          (body['lines'] as List?)?.map((line) => line.toString()).toList() ??
              const <String>[];
      setState(() {
        subtitlePreviewLines = lines;
        if (!silent) {
          message = '字幕预览已刷新';
          messageIsError = false;
        }
      });
    } catch (e) {
      if (!silent) showError(e.toString());
    }
  }

  Future<void> editSubtitlesAndPip() async {
    await refreshSubtitlePreview(silent: true);
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, dialogSetState) {
            void updateDialog(VoidCallback update) {
              setState(update);
              dialogSetState(() {});
            }

            return AlertDialog(
              backgroundColor: panelBg,
              title: const Text('编辑字幕及画中画'),
              content: SizedBox(
                width: 560,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SwitchListTile(
                        value: subtitlesEnabled,
                        onChanged: (value) =>
                            updateDialog(() => subtitlesEnabled = value),
                        title: const Text('字幕 启用'),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: _dropdown(
                              selectedSubtitleFont,
                              _subtitleFontOptions,
                              (value) {
                                if (value == null) return;
                                updateDialog(
                                    () => selectedSubtitleFont = value);
                              },
                              labels: _subtitleFontLabels,
                            ),
                          ),
                          const SizedBox(width: 8),
                          _subtitlePresetButton(
                            '黄字',
                            const Color(0xFFFFE600),
                            const Color(0x00000000),
                            updateDialog,
                          ),
                          const SizedBox(width: 8),
                          _subtitlePresetButton(
                            '白字',
                            const Color(0xFFFFFFFF),
                            const Color(0x00000000),
                            updateDialog,
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      _labeledSlider(
                        '字号',
                        subtitleSize,
                        12,
                        56,
                        (value) => updateDialog(() => subtitleSize = value),
                        subtitleSize.round().toString(),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: SwitchListTile(
                              value: pipEnabled,
                              onChanged: (value) =>
                                  updateDialog(() => pipEnabled = value),
                              title: const Text('画中画启用'),
                              contentPadding: EdgeInsets.zero,
                            ),
                          ),
                          const SizedBox(width: 8),
                          _ghostButton('上传画中画', () async {
                            await uploadPipAsset();
                            if (mounted) dialogSetState(() {});
                          }),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: _dropdown(
                              pipPosition,
                              _pipPositionOptions,
                              (value) {
                                if (value == null) return;
                                updateDialog(() => _setPipPosition(value));
                              },
                              labels: _pipPositionLabels,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Opacity(
                              opacity: pipPosition == 'fullscreen' ? 0.45 : 1,
                              child: IgnorePointer(
                                ignoring: pipPosition == 'fullscreen',
                                child: _labeledSlider(
                                  '画中画大小',
                                  pipScale,
                                  0.1,
                                  0.95,
                                  (value) => updateDialog(() {
                                    pipScale = value;
                                    _clampPipCustomPosition();
                                  }),
                                  pipPosition == 'fullscreen'
                                      ? '100%'
                                      : '${(pipScale * 100).round()}%',
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: _ghostButton(
                              '画中画全屏',
                              () => updateDialog(
                                () => _setPipPosition('fullscreen'),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: _ghostButton(
                              '自定义拖放',
                              () => updateDialog(
                                () => _setPipPosition('custom'),
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: _dropdown(
                              pipTimingMode,
                              _pipTimingOptions,
                              (value) {
                                if (value == null) return;
                                updateDialog(() => pipTimingMode = value);
                              },
                              labels: _pipTimingLabels,
                            ),
                          ),
                          if (pipTimingMode == 'time') ...[
                            const SizedBox(width: 8),
                            SizedBox(
                              width: 92,
                              child: _smallTextField(
                                pipStartController,
                                '开始秒',
                                updateDialog,
                              ),
                            ),
                            const SizedBox(width: 8),
                            SizedBox(
                              width: 92,
                              child: _smallTextField(
                                pipEndController,
                                '结束秒',
                                updateDialog,
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (pipTimingMode == 'sentence') ...[
                        const SizedBox(height: 8),
                        _smallTextField(
                          pipTriggerController,
                          '触发句子',
                          updateDialog,
                        ),
                      ],
                      const SizedBox(height: 12),
                      _subtitlePreviewBox(updateDialog: updateDialog),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () async {
                    await refreshSubtitlePreview();
                    if (mounted) dialogSetState(() {});
                  },
                  child: const Text('刷新'),
                ),
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('完成'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Widget _smallTextField(
    TextEditingController controller,
    String hint,
    void Function(VoidCallback update) updateDialog,
  ) {
    return SizedBox(
      height: 42,
      child: TextField(
        controller: controller,
        onChanged: (_) => updateDialog(() {}),
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        decoration: InputDecoration(
          hintText: hint,
          filled: true,
          fillColor: const Color(0xFF171A28),
          isDense: true,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(color: purpleLine.withValues(alpha: 0.45)),
          ),
          focusedBorder: const OutlineInputBorder(
            borderRadius: BorderRadius.all(Radius.circular(8)),
            borderSide: BorderSide(color: cyan, width: 1.2),
          ),
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        ),
      ),
    );
  }

  Future<void> render() async {
    if (!_ensureSoftwareActivated()) return;
    if (generationMode == 'cloud') {
      await renderCloud();
      return;
    }
    final taskId = task?['task_id'] as String?;
    if (taskId == null) return;
    final script = _renderScript;
    if (script.isEmpty) {
      setState(() => message = '请先生成或填写文案');
      return;
    }
    if (!_validateCompositionSettings()) return;
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
    if (generationMode == 'cloud') {
      await stopCloudRender();
      return;
    }
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

  Future<_CloudUploadFile> _digitalHumanSourceUploadFile() async {
    if (_isAndroidClient) {
      final path = mobileDigitalHumanPath.trim();
      if (path.isEmpty) throw Exception('请先选择数字人形象视频');
      final file = File(path);
      if (!await file.exists()) throw Exception('数字人形象视频不存在，请重新选择');
      final fileName = mobileDigitalHumanName.trim().isEmpty
          ? _fileNameFromPath(path)
          : mobileDigitalHumanName.trim();
      return _CloudUploadFile(
        kind: 'source_video',
        file: file,
        fileName: fileName,
        contentType: _contentTypeForPath(fileName),
      );
    }
    final digitalHumanId = selectedDigitalHuman.trim();
    if (digitalHumanId.isEmpty) {
      throw Exception('请先上传或选择数字人形象');
    }
    final profile = _digitalHumanProfile(digitalHumanId);
    final name = profile?['name']?.toString().trim();
    final preferredName = '${_safeUploadFileNameBase(
      (name == null || name.isEmpty) ? 'digital_human' : name,
    )}.mp4';
    final url = Uri.parse('$apiBase/api/digital-humans/reference').replace(
        queryParameters: {'digital_human_id': digitalHumanId}).toString();
    final localPath = await _downloadPreviewToTempFile(
      url,
      'digital_human_source',
      preferredFileName: preferredName,
    );
    final file = File(localPath);
    if (!await file.exists()) {
      throw Exception('数字人形象视频下载失败');
    }
    final fileName = _fileNameFromPath(localPath);
    return _CloudUploadFile(
      kind: 'source_video',
      file: file,
      fileName: fileName,
      contentType: _contentTypeForPath(fileName),
    );
  }

  String _safeUploadFileNameBase(String value) {
    final normalized = value.trim().replaceAll(RegExp(r'[\\/:*?"<>|]+'), '_');
    final compact = normalized.replaceAll(RegExp(r'\s+'), '_');
    return compact.isEmpty ? 'digital_human' : compact;
  }

  Future<void> renderCloud() async {
    if (!_ensureCloudAccountReady()) return;
    if (selectedDigitalHuman.isEmpty) {
      showError('请先上传或选择数字人形象');
      return;
    }
    final script = _renderScript;
    if (script.isEmpty) {
      showError('请先生成或填写文案');
      return;
    }
    if (!_validateCompositionSettings()) return;
    final duration = _cloudDurationSeconds();
    if (duration == null) {
      showError('请输入云端任务时长');
      return;
    }

    setState(() {
      loading = true;
      renderingVideo = true;
      cloudJob = null;
      cloudOutputUrl = '';
      cloudOutputLocalPath = '';
      outputRefresh++;
      message = '正在上传云端素材';
      messageIsError = false;
    });

    try {
      final sourceUpload = await _digitalHumanSourceUploadFile();
      final fileName = sourceUpload.fileName;
      final uploadFiles = <_CloudUploadFile>[
        sourceUpload,
      ];
      final voicePath = _hasFreshCloudVoice(script)
          ? cloudVoiceAudioPath
          : task?['extracted_audio_path'] as String? ?? '';
      var hasVoiceAudio = false;
      if (voicePath.isNotEmpty) {
        final voiceFile = File(voicePath);
        if (await voiceFile.exists()) {
          hasVoiceAudio = true;
          uploadFiles.add(
            _CloudUploadFile(
              kind: 'voice_audio',
              file: voiceFile,
              fileName: _fileNameFromPath(voicePath),
              contentType: _contentTypeForPath(voicePath),
            ),
          );
        }
      }
      if (!hasVoiceAudio) {
        throw Exception('请先点击“克隆声音”，声音生成完成后再生成成品视频');
      }
      if (pipEnabled && pipAssetId.isEmpty) {
        throw Exception('请先上传画中画素材');
      }
      final uploadSpecs = <Map<String, dynamic>>[];
      for (final item in uploadFiles) {
        uploadSpecs.add({
          'kind': item.kind,
          'file_name': item.fileName,
          'content_type': item.contentType,
          'file_size_bytes': await item.file.length(),
        });
      }
      final cloudBasePayload = {
        ..._renderPayload(script),
        'bgm_id': 'none',
        'bgm_volume': 0,
        'subtitle_enabled': false,
        'pip_enabled': false,
        'pip_asset_id': null,
        'source_file_name': fileName,
        'original_script': originalScriptController.text.trim(),
        'rewritten_script': rewrittenScriptController.text.trim(),
      };
      final sessionRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/upload-session'),
        headers: _cloudHeaders(),
        body: jsonEncode({
          'assets': uploadSpecs,
          'payload': cloudBasePayload,
        }),
      );
      _check(sessionRes);
      final uploadJob = _decodeMap(sessionRes);
      if (!mounted) return;
      setState(() {
        cloudJob = uploadJob;
        cloudOutputUrl = '';
        cloudOutputLocalPath = '';
      });
      final assets = (uploadJob['assets'] as List?) ?? const [];
      if (assets.length != uploadFiles.length ||
          assets.any((asset) => asset is! Map)) {
        throw Exception('云端没有返回素材上传链接');
      }
      final jobId = uploadJob['job_id'] as String;
      for (var index = 0; index < assets.length; index++) {
        final asset = (assets[index] as Map).cast<String, dynamic>();
        final uploadFile = uploadFiles[index];
        final upload = (asset['upload'] as Map).cast<String, dynamic>();
        final uploadSize = await uploadFile.file.length();

        setState(() {
          message =
              '正在上传素材到云端临时存储：${uploadFile.fileName} (${index + 1}/${assets.length})';
          messageIsError = false;
        });
        await _uploadFileToPresignedUrl(upload, uploadFile.file);

        final assetId = asset['asset_id'] as String;
        final uploadedRes = await http.post(
          Uri.parse(
              '$_cloudApiBase/api/client/jobs/$jobId/assets/$assetId/uploaded'),
          headers: _cloudHeaders(),
          body: jsonEncode({'file_size_bytes': uploadSize}),
        );
        _check(uploadedRes);
      }

      setState(() => message = '正在提交云端生成任务');
      final submittedRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/submit'),
        headers: _cloudHeaders(),
        body: jsonEncode({
          'duration_seconds': duration,
          'resolution': '1080p',
          'payload': cloudBasePayload,
        }),
      );
      _check(submittedRes);
      final submitted = _decodeMap(submittedRes);
      if (!mounted) return;
      setState(() {
        cloudJob = submitted;
        cloudEstimate = {
          'estimated_points': submitted['estimated_points'],
          'duration_seconds': duration,
          'resolution': '1080p',
        };
        loading = false;
        message = '云端任务已进入队列';
        messageIsError = false;
      });
      await loadCloudMe(silent: true);
      _startCloudPolling(jobId);
    } catch (e) {
      _stopCloudPolling();
      if (!mounted) return;
      setState(() {
        loading = false;
        renderingVideo = false;
        message = e.toString();
        messageIsError = true;
      });
    }
  }

  Future<void> _uploadFileToPresignedUrl(
    Map<String, dynamic> upload,
    File file,
  ) async {
    final fileSize = await file.length();
    final timeout = _cloudUploadTimeout(fileSize);
    try {
      await _uploadFileToPresignedUrlInner(upload, file, fileSize).timeout(
        timeout,
      );
    } on TimeoutException {
      throw TimeoutException(
        '上传素材到云端临时存储超时，已等待 ${timeout.inMinutes} 分钟，请检查网络后重试',
      );
    }
  }

  Future<Map<String, dynamic>> _runCloudPreprocess({
    required Map<String, dynamic> payload,
    File? sourceFile,
    String? sourceFileName,
  }) async {
    final preprocessPayload = {
      ...payload,
      'client': 'oral_video_agent_client',
    };
    String jobId;
    if (sourceFile != null) {
      final fileName = sourceFileName?.trim().isNotEmpty == true
          ? sourceFileName!.trim()
          : _fileNameFromPath(sourceFile.path);
      final uploadSpecs = [
        {
          'kind': 'source_video',
          'file_name': fileName,
          'content_type': _contentTypeForPath(fileName),
          'file_size_bytes': await sourceFile.length(),
        }
      ];
      final sessionRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/preprocess/upload-session'),
        headers: _cloudHeaders(),
        body: jsonEncode({
          'assets': uploadSpecs,
          'payload': preprocessPayload,
        }),
      );
      _check(sessionRes);
      final uploadJob = _decodeMap(sessionRes);
      jobId = uploadJob['job_id'] as String;
      if (!mounted) throw Exception('页面已关闭');
      setState(() => cloudJob = uploadJob);
      final assets = (uploadJob['assets'] as List?) ?? const [];
      if (assets.length != 1 || assets.first is! Map) {
        throw Exception('云端没有返回预处理素材上传链接');
      }
      final asset = (assets.first as Map).cast<String, dynamic>();
      final upload = (asset['upload'] as Map).cast<String, dynamic>();
      setState(() {
        message = '正在上传视频到云端提取文案';
        messageIsError = false;
      });
      await _uploadFileToPresignedUrl(upload, sourceFile);
      final uploadedRes = await http.post(
        Uri.parse(
          '$_cloudApiBase/api/client/jobs/$jobId/assets/${asset['asset_id']}/uploaded',
        ),
        headers: _cloudHeaders(),
        body: jsonEncode({'file_size_bytes': await sourceFile.length()}),
      );
      _check(uploadedRes);
      final submitRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/preprocess/jobs/$jobId/submit'),
        headers: _cloudHeaders(),
        body: jsonEncode({'payload': preprocessPayload}),
      );
      _check(submitRes);
      final submitted = _decodeMap(submitRes);
      if (mounted) setState(() => cloudJob = submitted);
    } else {
      final createRes = await http.post(
        Uri.parse('$_cloudApiBase/api/client/preprocess/jobs'),
        headers: _cloudHeaders(),
        body: jsonEncode({'payload': preprocessPayload}),
      );
      _check(createRes);
      final created = _decodeMap(createRes);
      jobId = created['job_id'] as String;
      if (mounted) setState(() => cloudJob = created);
    }
    return _waitCloudPreprocessResult(jobId);
  }

  Future<Map<String, dynamic>> _waitCloudPreprocessResult(
    String jobId, {
    Duration timeout = const Duration(minutes: 20),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      await Future.delayed(const Duration(seconds: 2));
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      if (!mounted) throw Exception('页面已关闭');
      final status = body['status']?.toString() ?? '';
      final percent = body['progress_percent'];
      setState(() {
        cloudJob = body;
        message = status == 'running' && percent is num
            ? '云端任务处理中：${percent.round()}%'
            : '云端任务：${_cloudStatusText(status)}';
        messageIsError = status == 'failed';
      });
      if (status == 'completed') {
        final result = (body['result'] as Map?)?.cast<String, dynamic>();
        if (result == null) throw Exception('云端任务没有返回结果');
        return result;
      }
      if (status == 'failed') {
        throw Exception(body['error_message']?.toString() ?? '云端任务失败');
      }
      if (status == 'canceled') {
        throw Exception('云端任务已取消');
      }
      if (status == 'timed_out') {
        throw Exception('云端任务排队超过 24 小时，已自动超时并移出队列');
      }
    }
    throw TimeoutException('云端任务等待超时');
  }

  Future<void> _uploadFileToPresignedUrlInner(
    Map<String, dynamic> upload,
    File file,
    int fileSize,
  ) async {
    final url = upload['url'] as String? ?? '';
    if (url.isEmpty) throw Exception('云端上传链接为空');
    final method = (upload['method'] as String? ?? 'PUT').toUpperCase();
    final headers = (upload['headers'] as Map? ?? const {})
        .map((key, value) => MapEntry('$key', '$value'));

    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 20);
    try {
      final request = await client.openUrl(method, Uri.parse(url));
      request.followRedirects = false;
      request.contentLength = fileSize;
      headers.forEach((key, value) {
        if (key.toLowerCase() == HttpHeaders.contentLengthHeader) return;
        request.headers.set(key, value);
      });
      await request.addStream(_trackedCosUploadStream(file, fileSize));
      final response = await request.close();
      final body = await utf8.decodeStream(response);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception('云端素材上传失败 ${response.statusCode}: $body');
      }
    } on SocketException catch (e) {
      throw Exception('云端素材上传连接失败: ${e.message}');
    } finally {
      client.close(force: true);
    }
  }

  Duration _cloudUploadTimeout(int fileSizeBytes) {
    final fileMiB = fileSizeBytes / (1024 * 1024);
    final minutes = math.max(5, math.min(60, (fileMiB / 2).ceil() + 3));
    return Duration(minutes: minutes);
  }

  Stream<List<int>> _trackedCosUploadStream(File file, int totalBytes) async* {
    var sent = 0;
    var lastPercent = -1;
    var lastUpdate = DateTime.fromMillisecondsSinceEpoch(0);
    await for (final chunk in file.openRead()) {
      sent += chunk.length;
      _updateCosUploadProgress(
        sent: sent,
        total: totalBytes,
        lastPercent: lastPercent,
        lastUpdate: lastUpdate,
        onUpdated: (percent, updateTime) {
          lastPercent = percent;
          lastUpdate = updateTime;
        },
      );
      yield chunk;
    }
  }

  void _updateCosUploadProgress({
    required int sent,
    required int total,
    required int lastPercent,
    required DateTime lastUpdate,
    required void Function(int percent, DateTime updateTime) onUpdated,
  }) {
    if (!mounted || total <= 0) return;
    final percent = ((sent / total) * 100).clamp(0, 100).floor();
    final now = DateTime.now();
    final shouldUpdate = sent >= total ||
        percent >= lastPercent + 5 ||
        now.difference(lastUpdate).inMilliseconds >= 600;
    if (!shouldUpdate) return;
    onUpdated(percent, now);
    setState(() {
      message =
          '正在上传素材到云端临时存储 $percent% (${_formatBytes(sent)} / ${_formatBytes(total)})';
      messageIsError = false;
    });
  }

  String _formatBytes(int bytes) {
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)}MB';
    }
    if (bytes >= 1024) {
      return '${(bytes / 1024).toStringAsFixed(1)}KB';
    }
    return '${bytes}B';
  }

  void _startCloudPolling(String jobId) {
    _stopCloudPolling();
    cloudPollTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      _pollCloudJob(jobId);
    });
  }

  void _stopCloudPolling() {
    cloudPollTimer?.cancel();
    cloudPollTimer = null;
  }

  Future<void> _pollCloudJob(String jobId) async {
    if (!_cloudLoggedIn || !_cloudLicensed) return;
    try {
      final res = await http.get(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId'),
        headers: _cloudHeaders(),
      );
      if (res.statusCode < 200 || res.statusCode >= 300) return;
      final body = _decodeMap(res);
      if (!mounted) return;
      final status = body['status'] as String? ?? '';
      setState(() {
        cloudJob = body;
        message = _cloudJobMessage(body);
        messageIsError = status == 'failed';
      });
      if (status == 'completed') {
        _stopCloudPolling();
        await _loadCloudDownload(jobId);
        await loadCloudMe(silent: true);
        if (_isAndroidClient) await loadMobileCloudJobs(silent: true);
        if (!mounted) return;
        setState(() {
          loading = false;
          renderingVideo = false;
          message = '云端视频已生成';
          messageIsError = false;
        });
      } else if (status == 'failed' ||
          status == 'canceled' ||
          status == 'timed_out') {
        _stopCloudPolling();
        await loadCloudMe(silent: true);
        if (_isAndroidClient) await loadMobileCloudJobs(silent: true);
        if (!mounted) return;
        setState(() {
          loading = false;
          renderingVideo = false;
        });
      }
    } catch (_) {
      // 临时网络抖动不终止云端任务轮诃69?    }
    }
  }

  Future<void> _loadCloudDownload(String jobId) async {
    if (cloudOutputLocalPath.isNotEmpty &&
        await File(cloudOutputLocalPath).exists()) {
      return;
    }
    final res = await http.get(
      Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/download'),
      headers: _cloudHeaders(),
    );
    _check(res);
    final body = _decodeMap(res);
    final download = (body['download'] as Map).cast<String, dynamic>();
    final url = download['url'] as String? ?? '';
    if (url.isEmpty) throw Exception('云端下载链接为空');
    final headers = (download['headers'] as Map? ?? const {})
        .map((key, value) => MapEntry('$key', '$value'));
    final cosKey = download['cos_key'] as String? ?? '';
    final fileName = _cloudOutputFileName(jobId, cosKey);
    if (mounted) {
      setState(() {
        message = '正在保存云端成品到本地';
        messageIsError = false;
      });
    }
    final localPath = await _downloadCloudOutputToLocal(
      url: url,
      headers: headers,
      fileName: fileName,
    );
    final finalPath = await _postprocessCloudOutputIfNeeded(localPath);
    if (!mounted) return;
    setState(() {
      cloudOutputUrl = url;
      cloudOutputLocalPath = finalPath;
      outputRefresh++;
      message = finalPath == localPath ? '云端成品已保存到本地' : '云端成品已完成本地合成';
      messageIsError = false;
    });
    try {
      await confirmCloudDownload(silent: true);
    } catch (_) {
      // The local file is already saved; scheduled cleanup still protects cloud storage.
    }
  }

  bool get _needsLocalCloudPostprocess {
    if (_isAndroidClient) return false;
    return subtitlesEnabled || selectedBgm != 'none' || pipEnabled;
  }

  Future<String> _postprocessCloudOutputIfNeeded(String sourcePath) async {
    if (!_needsLocalCloudPostprocess) return sourcePath;
    if (pipEnabled && pipAssetId.isEmpty) {
      throw Exception('请先上传画中画素材');
    }
    if (mounted) {
      setState(() {
        message = '正在本地合成字幕、BGM和画中画';
        messageIsError = false;
      });
    }
    final payload = {
      'source_video_path': sourcePath,
      'options': _renderPayload(_renderScript),
    };
    final res = await http.post(
      Uri.parse('$apiBase/api/videos/postprocess'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(payload),
    );
    _check(res);
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (body['ready'] != true) {
      throw Exception(body['detail'] as String? ?? '本地后处理合成失败');
    }
    final path = body['path'] as String? ?? '';
    if (path.isEmpty) throw Exception('本地后处理没有返回成品路径');
    return path;
  }

  Future<String> _downloadCloudJobOutputToLocal(
    String jobId, {
    required String fallbackFileName,
  }) async {
    final res = await http.get(
      Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/download'),
      headers: _cloudHeaders(),
    );
    _check(res);
    final body = _decodeMap(res);
    final download = (body['download'] as Map).cast<String, dynamic>();
    final url = download['url'] as String? ?? '';
    if (url.isEmpty) throw Exception('云端下载链接为空');
    final headers = (download['headers'] as Map? ?? const {})
        .map((key, value) => MapEntry('$key', '$value'));
    final cosKey = download['cos_key'] as String? ?? '';
    final fileName = _cloudGenericOutputFileName(
      jobId,
      cosKey,
      fallbackFileName: fallbackFileName,
    );
    if (mounted) {
      setState(() {
        message = '正在保存云端文件到本地';
        messageIsError = false;
      });
    }
    return _downloadCloudOutputToLocal(
      url: url,
      headers: headers,
      fileName: fileName,
    );
  }

  String _cloudGenericOutputFileName(
    String jobId,
    String cosKey, {
    required String fallbackFileName,
  }) {
    final rawName = cosKey.trim().isEmpty
        ? fallbackFileName
        : Uri.decodeComponent(_fileNameFromPath(cosKey));
    final safeName =
        rawName.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_').trim();
    final name = safeName.isEmpty ? fallbackFileName : safeName;
    final hasExtension = RegExp(r'\.[A-Za-z0-9]{2,5}$').hasMatch(name);
    final fallbackExtension =
        RegExp(r'\.[A-Za-z0-9]{2,5}$').firstMatch(fallbackFileName)?.group(0) ??
            '';
    final withExt = hasExtension || fallbackExtension.isEmpty
        ? name
        : '$name$fallbackExtension';
    return '$jobId-$withExt';
  }

  String _cloudOutputFileName(String jobId, String cosKey) {
    final rawName = cosKey.trim().isEmpty
        ? 'result.mp4'
        : Uri.decodeComponent(_fileNameFromPath(cosKey));
    final safeName =
        rawName.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_').trim();
    final name = safeName.isEmpty ? 'result.mp4' : safeName;
    final lower = name.toLowerCase();
    final withExt = lower.endsWith('.mp4') ? name : '$name.mp4';
    return '$jobId-$withExt';
  }

  Future<File> _cloudOutputFile(String fileName) async {
    final dir = await getApplicationSupportDirectory();
    final outputDir = Directory('${dir.path}${Platform.pathSeparator}outputs');
    await outputDir.create(recursive: true);
    return File('${outputDir.path}${Platform.pathSeparator}$fileName');
  }

  Future<String> _downloadCloudOutputToLocal({
    required String url,
    required Map<String, String> headers,
    required String fileName,
  }) async {
    final dest = await _cloudOutputFile(fileName);
    final tmp = File('${dest.path}.download');
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 20);
    IOSink? sink;
    try {
      final request = await client.getUrl(Uri.parse(url));
      headers.forEach((key, value) {
        request.headers.set(key, value);
      });
      final response = await request.close();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await utf8.decodeStream(response);
        throw Exception('云端成品下载失败 ${response.statusCode}: $body');
      }
      final total = response.contentLength;
      var received = 0;
      var lastUpdate = DateTime.fromMillisecondsSinceEpoch(0);
      sink = tmp.openWrite();
      await for (final chunk in response) {
        received += chunk.length;
        sink.add(chunk);
        final now = DateTime.now();
        if (mounted &&
            total > 0 &&
            now.difference(lastUpdate).inMilliseconds >= 600) {
          lastUpdate = now;
          final percent = ((received / total) * 100).clamp(0, 100).floor();
          setState(() {
            message =
                '正在保存云端成品到本地 $percent% (${_formatBytes(received)} / ${_formatBytes(total)})';
            messageIsError = false;
          });
        }
      }
      await sink.close();
      sink = null;
      if (await dest.exists()) {
        await dest.delete();
      }
      await tmp.rename(dest.path);
      final saved = File(dest.path);
      if (!await saved.exists() || await saved.length() == 0) {
        throw Exception('本地成品文件保存失败');
      }
      return saved.path;
    } finally {
      if (sink != null) {
        await sink.close();
      }
      client.close(force: true);
      if (await tmp.exists()) {
        await tmp.delete();
      }
    }
  }

  Future<void> stopCloudRender() async {
    final jobId = _cloudJobId;
    if (jobId == null) {
      _stopCloudPolling();
      setState(() {
        loading = false;
        renderingVideo = false;
        message = '已重置云端生成状态';
        messageIsError = false;
      });
      return;
    }
    try {
      final res = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/cancel'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      _stopCloudPolling();
      setState(() {
        cloudJob = body;
        loading = false;
        renderingVideo = false;
        message = '云端任务已取消';
        messageIsError = false;
      });
      await loadCloudMe(silent: true);
      if (_isAndroidClient) await loadMobileCloudJobs(silent: true);
    } catch (e) {
      _stopCloudPolling();
      if (!mounted) return;
      setState(() {
        loading = false;
        renderingVideo = false;
        message = e.toString();
        messageIsError = true;
      });
    }
  }

  Future<void> confirmCloudDownload({bool silent = false}) async {
    final jobId = _cloudJobId;
    if (jobId == null) {
      showError('没有可确认的云端任务');
      return;
    }
    Future<void> action() async {
      final res = await http.post(
        Uri.parse('$_cloudApiBase/api/client/jobs/$jobId/download-confirmed'),
        headers: _cloudHeaders(),
      );
      _check(res);
      final body = _decodeMap(res);
      setState(() {
        cloudJob = (body['job'] as Map?)?.cast<String, dynamic>() ?? cloudJob;
        if (!silent) {
          message = '已确认下载，云端临时文件已清理';
          messageIsError = false;
        }
      });
    }

    if (silent) {
      await action();
    } else {
      await _runBusy(action);
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
    if (generationMode == 'cloud') {
      final jobId = _cloudJobId;
      if (cloudOutputLocalPath.isEmpty &&
          jobId != null &&
          (cloudJob?['status'] as String?) == 'completed') {
        await _loadCloudDownload(jobId);
      }
      final url = cloudOutputLocalPath.isNotEmpty
          ? cloudOutputLocalPath
          : cloudOutputUrl;
      if (url.isEmpty) {
        showError('请先完成云端生成任务');
        return;
      }
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _VideoPlayerDialog(url: url),
      );
      return;
    }
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
    if (generationMode == 'cloud') {
      final jobId = _cloudJobId;
      if (cloudOutputLocalPath.isEmpty &&
          jobId != null &&
          (cloudJob?['status'] as String?) == 'completed') {
        await _loadCloudDownload(jobId);
      }
      final path = cloudOutputLocalPath;
      if (path.isNotEmpty && await File(path).exists()) {
        await _openLocalVideoPath(path);
        return;
      }
      final url = cloudOutputUrl;
      if (url.isEmpty) {
        showError('还没有可打开的云端成品视频');
        return;
      }
      await _openExternalUrl(url);
      return;
    }
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

  Future<void> _openLocalVideoPath(String path) async {
    try {
      if (Platform.isWindows) {
        await Process.start('explorer.exe', ['/select,', path]);
      } else if (Platform.isMacOS) {
        await Process.start('open', ['-R', path]);
      } else {
        await Process.start('xdg-open', [File(path).parent.path]);
      }
    } catch (e) {
      showError('打开视频失败：$e');
    }
  }

  Future<void> _openExternalUrl(String url) async {
    try {
      if (Platform.isWindows) {
        await Process.start('cmd', ['/c', 'start', '', url]);
      } else if (Platform.isMacOS) {
        await Process.start('open', [url]);
      } else {
        await Process.start('xdg-open', [url]);
      }
    } catch (e) {
      showError('打开链接失败：$e');
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
      showError(_friendlyError(e));
    } finally {
      if (mounted && !renderingVideo) {
        setState(() => loading = false);
      }
    }
  }

  String _friendlyError(Object error) {
    final text = error.toString();
    const prefix = 'Exception: ';
    const timeoutPrefix = 'TimeoutException: ';
    if (text.startsWith(prefix)) return text.substring(prefix.length);
    if (text.startsWith(timeoutPrefix)) {
      return text.substring(timeoutPrefix.length);
    }
    return text;
  }

  String get _renderScript {
    final rewritten = rewrittenScriptController.text.trim();
    if (rewritten.isNotEmpty) return rewritten;
    return originalScriptController.text.trim();
  }

  String _voiceKeyFor(String script) =>
      '$selectedVoice:${script.trim().hashCode}';

  bool _hasFreshCloudVoice(String script) {
    if (cloudVoiceAudioPath.isEmpty) return false;
    if (generatedVoiceKey != _voiceKeyFor(script)) return false;
    return File(cloudVoiceAudioPath).existsSync();
  }

  void _invalidateGeneratedVoice() {
    cloudVoiceAudioPath = '';
    cloudVoiceJobId = '';
    generatedVoiceKey = '';
  }

  Map<String, dynamic> _renderPayload(String script) {
    final pipRect = _pipNormalizedRect();
    return {
      'script': script,
      'voice_id': selectedVoice,
      'voice_volume': voicePreviewVolume,
      'digital_human_engine': selectedDigitalHumanEngine,
      'digital_human_id': selectedDigitalHuman.startsWith('custom:') ||
              selectedDigitalHuman.startsWith('template:')
          ? selectedDigitalHuman
          : null,
      'motion_mode': randomMotion ? 'random' : 'loop',
      'expression_mode': toothHd ? 'sync' : 'basic',
      'bgm_id': selectedBgm,
      'bgm_volume': bgmVolume,
      'subtitle_enabled': subtitlesEnabled,
      'subtitle_style': _subtitleStylePayload(),
      'pip_enabled': pipEnabled,
      'pip_asset_id': pipAssetId.isEmpty ? null : pipAssetId,
      'pip_position': pipPosition,
      'pip_scale': pipScale,
      'pip_x': pipRect.left,
      'pip_y': pipRect.top,
      'pip_width': pipRect.width,
      'pip_height': pipRect.height,
      'pip_timing_mode': pipTimingMode,
      'pip_start_seconds': _optionalSeconds(pipStartController.text),
      'pip_end_seconds': _optionalSeconds(pipEndController.text),
      'pip_trigger_text': pipTriggerController.text.trim().isEmpty
          ? null
          : pipTriggerController.text.trim(),
    };
  }

  double? _optionalSeconds(String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return null;
    return double.tryParse(trimmed.replaceAll('，', '.'));
  }

  bool _validateCompositionSettings() {
    if (!pipEnabled) return true;
    if (pipAssetId.isEmpty) {
      showError('请先上传画中画素材');
      return false;
    }
    if (pipTimingMode == 'time') {
      final start = _optionalSeconds(pipStartController.text);
      final end = _optionalSeconds(pipEndController.text);
      if (start == null) {
        showError('请填写画中画开始秒数');
        return false;
      }
      if (end != null && end <= start) {
        showError('画中画结束秒数必须大于开始秒数');
        return false;
      }
    }
    if (pipTimingMode == 'sentence' &&
        pipTriggerController.text.trim().isEmpty) {
      showError('请填写画中画触发句子');
      return false;
    }
    return true;
  }

  Map<String, dynamic> _subtitleStylePayload() {
    return {
      'font_size': subtitleSize.round(),
      'color': _colorHex(subtitleColor),
      'outline_color': _colorHex(subtitleOutlineColor),
      'outline_width': 2,
      'font_family': selectedSubtitleFont,
      'position': 'bottom',
      'margin_v': 70,
      'max_chars_per_line': 12,
    };
  }

  String _colorHex(Color color) {
    final rgb = color.toARGB32() & 0x00FFFFFF;
    return '#${rgb.toRadixString(16).padLeft(6, '0').toUpperCase()}';
  }

  String? get _taskId => task?['task_id'] as String?;

  String? get _cloudJobId => cloudJob?['job_id'] as String?;

  String get _cloudAccountText {
    if (!_cloudLicensed) return '软件未激活';
    final email = _cloudUser?['email'] as String? ?? '';
    if (email.trim().isEmpty) return '未绑定邮箱账号';
    return email;
  }

  bool get _cloudVoiceJobActive {
    final jobId = cloudVoiceJobId.trim();
    if (jobId.isEmpty) return false;
    final currentJobId = cloudJob?['job_id']?.toString() ?? '';
    final status = cloudJob?['status']?.toString() ?? '';
    return currentJobId == jobId &&
        const {'uploading', 'queued', 'running'}.contains(status);
  }

  String get _latestLedgerText {
    if (cloudLedger.isEmpty) return '暂无流水';
    final item = cloudLedger.first;
    final points = item['points'] ?? 0;
    final positive = points is num && points > 0;
    return '${_ledgerTitle(item)} ${positive ? '+' : ''}$points';
  }

  String get _cloudOutputLabel {
    if (cloudOutputLocalPath.isNotEmpty) {
      return _fileNameFromPath(cloudOutputLocalPath);
    }
    if (cloudOutputUrl.isNotEmpty) return '云端成品已生成';
    final status = cloudJob?['status'] as String?;
    if (status != null && status.isNotEmpty) return _cloudStatusText(status);
    return '云端成品生成后自动关联';
  }

  String get _voiceServiceText {
    if (generationMode == 'cloud' && providers?['voice_online'] != true) {
      return '云端处理';
    }
    if (providers?['voice_online'] == true ||
        providers?['voice_provider'] == 'placeholder') {
      return '已启动';
    }
    return '未启动';
  }

  String? get _sourceVideoUrl {
    final taskId = _taskId;
    final taskSourceUrl = taskId != null && task?['source_video'] != null
        ? '$apiBase/api/tasks/$taskId/source'
        : null;
    if (generationMode == 'cloud') {
      return cloudSourceVideoPath.isEmpty
          ? taskSourceUrl
          : cloudSourceVideoPath;
    }
    return taskSourceUrl;
  }

  String? get _outputVideoUrl {
    if (generationMode == 'cloud') {
      if (cloudOutputLocalPath.isNotEmpty) return cloudOutputLocalPath;
      return cloudOutputUrl.isEmpty ? null : cloudOutputUrl;
    }
    final taskId = _taskId;
    if (taskId == null) return null;
    final hasOutputPath = (output?['ready'] == true) ||
        ((task?['output_video_path'] as String? ?? '').isNotEmpty);
    if (!hasOutputPath) return null;
    return '$apiBase/api/tasks/$taskId/download?v=$outputRefresh';
  }

  String get _selectedBgmUrl {
    return Uri.parse('$apiBase/api/bgm/preview').replace(queryParameters: {
      'bgm_id': selectedBgm,
    }).toString();
  }

  String get _selectedVoicePreviewUrl {
    return Uri.parse('$apiBase/api/voices/preview')
        .replace(queryParameters: {'voice_id': selectedVoice}).toString();
  }

  String? get _generatedVoiceUrl {
    final script = _renderScript;
    if (generationMode == 'cloud' && _hasFreshCloudVoice(script)) {
      return cloudVoiceAudioPath;
    }
    final taskId = _taskId;
    final hasGeneratedVoice =
        (task?['extracted_audio_path'] as String? ?? '').isNotEmpty;
    if (taskId == null || !hasGeneratedVoice) return null;
    return '$apiBase/api/tasks/$taskId/voice?v=$outputRefresh';
  }

  String? get _outputVideoPath {
    if (generationMode == 'cloud') {
      return cloudOutputLocalPath.isEmpty ? null : cloudOutputLocalPath;
    }
    final outputPath = output?['path'] as String?;
    if (outputPath != null && outputPath.isNotEmpty) return outputPath;
    final taskPath = task?['output_video_path'] as String?;
    if (taskPath != null && taskPath.isNotEmpty) return taskPath;
    return null;
  }

  String _fileNameFromPath(String path) {
    return path.split(RegExp(r'[\\/]')).last;
  }

  String _contentTypeForPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.wav')) return 'audio/wav';
    if (lower.endsWith('.mp3')) return 'audio/mpeg';
    if (lower.endsWith('.m4a')) return 'audio/mp4';
    if (lower.endsWith('.aac')) return 'audio/aac';
    if (lower.endsWith('.flac')) return 'audio/flac';
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.mov')) return 'video/quicktime';
    if (lower.endsWith('.mkv')) return 'video/x-matroska';
    if (lower.endsWith('.webm')) return 'video/webm';
    return 'video/mp4';
  }

  String _cloudStatusText(String status) {
    return switch (status) {
      'uploading' => '等待上传',
      'queued' => '排队中',
      'running' => '生成中',
      'completed' => '已完成',
      'failed' => '失败',
      'canceled' => '已取消',
      'timed_out' => '已超时',
      _ => status,
    };
  }

  String _cloudJobMessage(Map<String, dynamic> job) {
    final status = job['status'] as String? ?? '';
    final message = job['error_message'] as String? ?? '';
    if (status == 'failed' && message.isNotEmpty) return message;
    final percent = job['progress_percent'];
    if (status == 'running' && percent is num) {
      return '云端生成中：${percent.round()}%';
    }
    return '云端任务：${_cloudStatusText(status)}';
  }

  String _ledgerTitle(Map<String, dynamic> item) {
    final event = item['event_type'] as String? ?? '';
    final source = item['source'] as String? ?? '';
    final sourceText = source == 'bonus' ? '赠点' : '付费点数';
    return switch (event) {
      'admin_credit' => '后台加点',
      'credit_redeem' => '兑换加点',
      'hold' => '任务冻结',
      'capture' => '任务扣点',
      'release' => '任务释放',
      'cancel_fee' => '取消扣费',
      _ => '$event $sourceText',
    };
  }

  @override
  Widget build(BuildContext context) {
    if (!initialized) {
      return _gateScaffold('正在启动软件');
    }
    if (_isAndroidClient) {
      if (!_cloudLoggedIn || !_cloudAccountBound) {
        return _mobileAuthScaffold();
      }
      return _mobileWorkbenchScaffold();
    }
    if (!_cloudLicensed) {
      return _gateScaffold('请先激活软件', showActivationActions: true);
    }
    return Scaffold(
      body: Row(
        children: [
          _workspaceSidebar(),
          Expanded(
            child: Column(
              children: [
                _workspaceTopBar(),
                Expanded(child: _workspaceBody()),
                if (message.isNotEmpty) _messageBar(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _workspaceBody() {
    return switch (selectedSection) {
      _WorkspaceSection.studio => _studioPage(),
      _WorkspaceSection.voices => _voiceManagementPage(),
      _WorkspaceSection.avatars => _avatarManagementPage(),
      _WorkspaceSection.media => _mediaManagementPage(),
      _WorkspaceSection.tasks => _taskCenterPage(),
      _WorkspaceSection.accounts => _accountManagementPage(),
      _WorkspaceSection.cloudAccount => _cloudAccountPage(),
    };
  }

  Widget _studioPage() {
    final studioTheme = ThemeData(
      brightness: Brightness.light,
      useMaterial3: true,
      fontFamilyFallback: const [
        'Microsoft YaHei UI',
        'Microsoft YaHei',
        'PingFang SC',
      ],
      colorScheme: ColorScheme.fromSeed(
        seedColor: studioPrimary,
        brightness: Brightness.light,
        primary: studioPrimary,
        surface: Colors.white,
      ),
      dividerColor: studioBorder,
      textTheme: ThemeData.light().textTheme.apply(
            bodyColor: studioInk,
            displayColor: studioInk,
          ),
      sliderTheme: const SliderThemeData(
        activeTrackColor: studioPrimary,
        thumbColor: studioPrimary,
        inactiveTrackColor: Color(0xFFE7E9F2),
      ),
    );
    return Theme(
      data: studioTheme,
      child: DefaultTextStyle(
        style: studioTheme.textTheme.bodyMedium!.copyWith(color: studioInk),
        child: ColoredBox(
          color: studioCanvas,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 1180;
              if (compact) {
                return SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 24),
                  child: Column(
                    children: [
                      _studioStepCard(compact: true),
                      const SizedBox(height: 14),
                      SizedBox(
                        height: 620,
                        child: _studioPreviewPanel(),
                      ),
                    ],
                  ),
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(child: _studioStepCard()),
                  SizedBox(width: 326, child: _studioPreviewPanel()),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  List<({String title, String subtitle, IconData icon})> get _studioSteps =>
      const [
        (
          title: '文案生成',
          subtitle: '导入链接并智能改写',
          icon: Icons.edit_note_rounded,
        ),
        (
          title: '声音生成',
          subtitle: '选择音色与克隆声音',
          icon: Icons.graphic_eq_rounded,
        ),
        (
          title: '数字人生成',
          subtitle: '选择形象并生成视频',
          icon: Icons.face_retouching_natural_rounded,
        ),
        (
          title: '视频封面',
          subtitle: '生成或上传竖版封面',
          icon: Icons.image_outlined,
        ),
        (
          title: 'BGM 与字幕',
          subtitle: '完善声音和字幕样式',
          icon: Icons.subtitles_rounded,
        ),
        (
          title: '一键发布',
          subtitle: '编辑文案并选择平台',
          icon: Icons.rocket_launch_rounded,
        ),
      ];

  Widget _studioWorkflowRail({bool embedded = false}) {
    final steps = _studioSteps;
    return Container(
      margin:
          embedded ? EdgeInsets.zero : const EdgeInsets.fromLTRB(16, 16, 8, 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(embedded ? 0 : 18),
        border: embedded ? null : Border.all(color: studioBorder),
        boxShadow: embedded
            ? null
            : const [
                BoxShadow(
                  color: Color(0x0A111827),
                  blurRadius: 24,
                  offset: Offset(0, 8),
                ),
              ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 20, 18, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(
                        color: const Color(0xFFEEF0FF),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Icon(
                        Icons.auto_awesome_rounded,
                        color: studioPrimary,
                        size: 19,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'AI 创作工作流',
                        style: TextStyle(
                          color: studioInk,
                          fontSize: 15,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Text(
                      '整体进度',
                      style: TextStyle(
                        color: studioMuted,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const Spacer(),
                    Text(
                      '${studioStep + 1}/${steps.length}',
                      style: const TextStyle(
                        color: studioPrimary,
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 7),
                ClipRRect(
                  borderRadius: BorderRadius.circular(99),
                  child: LinearProgressIndicator(
                    minHeight: 6,
                    value: (studioStep + 1) / steps.length,
                    backgroundColor: const Color(0xFFEEF0F4),
                    color: studioPrimary,
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
              itemCount: steps.length,
              itemBuilder: (context, index) =>
                  _studioStepNavItem(index, steps[index]),
            ),
          ),
          if (!embedded)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 18),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFF7F8FC),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: localApiOnline
                            ? studioSuccess
                            : const Color(0xFFFF6B7B),
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        localApiOnline ? '创作服务运行正常' : '等待本地服务连接',
                        style: const TextStyle(
                          color: studioMuted,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _studioStepNavItem(
    int index,
    ({String title, String subtitle, IconData icon}) step,
  ) {
    final active =
        selectedSection == _WorkspaceSection.studio && studioStep == index;
    final completed = index < studioStep;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () => setState(() {
            selectedSection = _WorkspaceSection.studio;
            studioStep = index;
          }),
          borderRadius: BorderRadius.circular(12),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
            decoration: BoxDecoration(
              color: active ? const Color(0xFFF0F1FF) : Colors.transparent,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: active ? const Color(0xFFD8DAFF) : Colors.transparent,
              ),
            ),
            child: Row(
              children: [
                Container(
                  width: 31,
                  height: 31,
                  decoration: BoxDecoration(
                    color: completed
                        ? const Color(0xFFE8F8F0)
                        : active
                            ? studioPrimary
                            : const Color(0xFFF0F2F6),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    completed ? Icons.check_rounded : step.icon,
                    size: 17,
                    color: completed
                        ? studioSuccess
                        : active
                            ? Colors.white
                            : const Color(0xFF9AA0B2),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        step.title,
                        style: TextStyle(
                          color: active ? studioPrimaryDark : studioInk,
                          fontSize: 13,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        step.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: studioMuted,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // Retained for possible future tablet navigation.
  // ignore: unused_element
  Widget _studioCompactSteps() {
    final steps = _studioSteps;
    return Container(
      height: 86,
      color: Colors.white,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: steps.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final active = studioStep == index;
          final completed = index < studioStep;
          return InkWell(
            onTap: () => setState(() => studioStep = index),
            borderRadius: BorderRadius.circular(12),
            child: Container(
              width: 138,
              padding: const EdgeInsets.symmetric(horizontal: 11),
              decoration: BoxDecoration(
                color: active ? const Color(0xFFF0F1FF) : Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: active ? const Color(0xFFD8DAFF) : studioBorder,
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    completed ? Icons.check_circle : steps[index].icon,
                    color: completed
                        ? studioSuccess
                        : active
                            ? studioPrimary
                            : studioMuted,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      steps[index].title,
                      style: TextStyle(
                        color: active ? studioPrimaryDark : studioInk,
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _studioStepCard({bool compact = false}) {
    final step = _studioSteps[studioStep];
    final content = Padding(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 26),
      child: _studioCurrentStep(),
    );
    return Container(
      margin: EdgeInsets.fromLTRB(8, 16, compact ? 8 : 8, compact ? 0 : 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: studioBorder),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A111827),
            blurRadius: 24,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: compact ? MainAxisSize.min : MainAxisSize.max,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 20, 20, 17),
            child: Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: const Color(0xFFEEF0FF),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(step.icon, color: studioPrimary, size: 23),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        step.title,
                        style: const TextStyle(
                          color: studioInk,
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        step.subtitle,
                        style: const TextStyle(
                          color: studioMuted,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF4F5F8),
                    borderRadius: BorderRadius.circular(99),
                  ),
                  child: Text(
                    '步骤 ${studioStep + 1} / ${_studioSteps.length}',
                    style: const TextStyle(
                      color: studioMuted,
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          if (compact)
            content
          else
            Expanded(child: SingleChildScrollView(child: content)),
          const Divider(height: 1),
          _studioStepFooter(),
        ],
      ),
    );
  }

  Widget _studioStepFooter() {
    final lastStep = studioStep == _studioSteps.length - 1;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
      child: Row(
        children: [
          TextButton.icon(
            onPressed:
                studioStep == 0 ? null : () => setState(() => studioStep -= 1),
            icon: const Icon(Icons.arrow_back_rounded, size: 18),
            label: const Text('上一步'),
          ),
          const Spacer(),
          FilledButton.icon(
            onPressed: loading
                ? null
                : lastStep
                    ? createPublishJobs
                    : () => setState(() => studioStep += 1),
            style: FilledButton.styleFrom(
              backgroundColor: studioPrimary,
              foregroundColor: Colors.white,
              minimumSize: const Size(132, 44),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            icon: Icon(
              lastStep
                  ? Icons.rocket_launch_rounded
                  : Icons.arrow_forward_rounded,
              size: 18,
            ),
            label: Text(lastStep ? '创建发布任务' : '保存并继续'),
          ),
        ],
      ),
    );
  }

  Widget _studioCurrentStep() {
    return switch (studioStep) {
      0 => _studioScriptStep(),
      1 => _studioVoiceStep(),
      2 => _studioAvatarStep(),
      3 => _studioCoverStep(),
      4 => _studioMediaStep(),
      _ => _studioPublishStep(),
    };
  }

  Widget _studioScriptStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip(
          '从同行视频链接提取口播文案，也可以直接上传本地视频。AI 会保留核心卖点并重写表达。',
        ),
        const SizedBox(height: 18),
        _studioFieldCard(
          title: '导入对标视频',
          subtitle: '支持抖音分享链接、完整分享文案或本地视频',
          icon: Icons.link_rounded,
          child: Column(
            children: [
              _input(urlController, '粘贴抖音分享链接或完整分享文案'),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(child: _stepButton('提取视频文案', createTask)),
                  const SizedBox(width: 10),
                  _ghostButton('上传本地视频', uploadSourceVideo),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        LayoutBuilder(
          builder: (context, constraints) {
            final stacked = constraints.maxWidth < 720;
            final original = _studioFieldCard(
              title: '原始文案',
              subtitle: '提取后仍可手动校正内容',
              icon: Icons.article_outlined,
              child: _textBox(originalScriptController, '等待提取原文案', 10),
            );
            final rewritten = _studioFieldCard(
              title: 'AI 改写',
              subtitle: '选择表达风格并补充受众与产品',
              icon: Icons.auto_fix_high_rounded,
              child: Column(
                children: [
                  _styleDropdown(),
                  const SizedBox(height: 9),
                  Row(
                    children: [
                      Expanded(child: _input(audienceController, '目标人群')),
                      const SizedBox(width: 8),
                      Expanded(child: _input(productController, '产品 / 服务')),
                    ],
                  ),
                  const SizedBox(height: 9),
                  _stepButton('生成改写文案', rewrite),
                  const SizedBox(height: 9),
                  _textBox(rewrittenScriptController, 'AI 改写结果', 8),
                ],
              ),
            );
            if (stacked) {
              return Column(
                children: [original, const SizedBox(height: 14), rewritten],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: original),
                const SizedBox(width: 14),
                Expanded(child: rewritten),
              ],
            );
          },
        ),
      ],
    );
  }

  Widget _studioVoiceStep() {
    final voiceOptions = _limitedProfileOptions(
      voices,
      'voice_id',
      preferredSystemPrefix: 'clone:',
    );
    final voiceLabels = {
      for (final voice in voices)
        voice['voice_id'] as String: voice['name'] as String,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip('选择已有音色直接合成，或上传 15–60 秒清晰人声创建专属声音。'),
        const SizedBox(height: 18),
        _studioFieldCard(
          title: '声音模型',
          subtitle: '当前服务：$_voiceServiceText',
          icon: Icons.record_voice_over_rounded,
          trailing: _studioStatusPill(
            _cloudVoiceJobActive ? '克隆中' : '服务可用',
            _cloudVoiceJobActive ? const Color(0xFFFFA726) : studioSuccess,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '选择声音',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 7),
              _dropdown(
                selectedVoice,
                voiceOptions,
                (value) => setState(() {
                  selectedVoice = value ?? selectedVoice;
                  _invalidateGeneratedVoice();
                }),
                labels: voiceLabels,
              ),
              const SizedBox(height: 16),
              _studioSlider(
                '语速',
                '调节口播节奏',
                speechRate,
                0.6,
                1.4,
                (value) => setState(() => speechRate = value),
                '${speechRate.toStringAsFixed(1)}x',
              ),
              const SizedBox(height: 10),
              _studioSlider(
                '试听音量',
                '仅影响本地试听',
                voicePreviewVolume,
                0,
                1,
                _updateVoicePreviewVolume,
                '${(voicePreviewVolume * 100).round()}%',
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 9,
                runSpacing: 9,
                children: [
                  _ghostButton('上传声音', uploadVoice),
                  _stepButton(
                    _cloudVoiceJobActive ? '停止克隆' : '克隆声音',
                    _cloudVoiceJobActive ? stopCloudVoiceJob : cloneVoice,
                    compact: true,
                    allowWhileLoading: _cloudVoiceJobActive,
                  ),
                  _ghostButton(
                    _isPlayingVoice ? '停止试听' : '试听声音',
                    playVoice,
                  ),
                  _ghostButton(
                    _isPlayingOriginalAudio ? '停止原音' : '试听原音',
                    playOriginalAudio,
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _studioAvatarStep() {
    final userDigitalHumans =
        digitalHumans.where((item) => item['built_in'] != true).toList();
    final options = _limitedProfileOptions(
      userDigitalHumans,
      'digital_human_id',
      preferredSystemPrefix: 'custom:',
    );
    final labels = {
      for (final human in userDigitalHumans)
        human['digital_human_id'] as String: human['name'] as String,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip('选择已授权的数字人形象，系统会将改写文案、声音和画面合成为竖版视频。'),
        const SizedBox(height: 18),
        _studioFieldCard(
          title: '数字人形象',
          subtitle: options.isEmpty ? '还没有可用形象，请先上传素材' : '点击列表选择本次出镜形象',
          icon: Icons.face_rounded,
          trailing: Wrap(
            spacing: 8,
            children: [
              _ghostButton('上传形象', uploadDigitalHuman),
              _ghostButton('删除', deleteDigitalHuman),
            ],
          ),
          child: _digitalHumanPicker(options, labels),
        ),
        const SizedBox(height: 14),
        _studioFieldCard(
          title: '合成设置',
          subtitle: _engineStatusText(),
          icon: Icons.movie_creation_outlined,
          child: Column(
            children: [
              Row(
                children: [
                  Expanded(child: _studioChoiceTile('单形象', '稳定生成，适合口播', true)),
                  const SizedBox(width: 10),
                  Expanded(child: _studioChoiceTile('多镜头', '即将开放', false)),
                ],
              ),
              const SizedBox(height: 14),
              _stepButton(
                renderingVideo ? '停止生成' : '生成数字人成品视频',
                renderingVideo ? stopRender : render,
                allowWhileLoading: renderingVideo,
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _studioCoverStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip('根据文案智能生成竖版封面，也可以上传已经设计好的 9:16 图片。'),
        const SizedBox(height: 18),
        _studioFieldCard(
          title: '视频封面',
          subtitle: '建议尺寸 1080 × 1920，主体和标题保持在安全区域内',
          icon: Icons.image_outlined,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _coverTools(),
              const SizedBox(height: 14),
              _coverPreview(),
            ],
          ),
        ),
      ],
    );
  }

  Widget _studioMediaStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip('统一配置背景音乐、字幕样式和画中画素材，所有设置会在最终合成时生效。'),
        const SizedBox(height: 18),
        _studioFieldCard(
          title: '声音与字幕',
          subtitle: '在背景音乐和字幕设置之间切换',
          icon: Icons.library_music_outlined,
          child: Column(
            children: [
              _subTabs(),
              const SizedBox(height: 18),
              _mediaSubTabPanel(),
            ],
          ),
        ),
      ],
    );
  }

  Widget _studioPublishStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _studioTip('选择发布平台与账号，补充标题、正文和话题后创建发布任务。'),
        const SizedBox(height: 18),
        _publisherPanel(),
      ],
    );
  }

  Widget _studioPreviewPanel() {
    final sourceUrl = _sourceVideoUrl;
    final outputUrl = _outputVideoUrl;
    final avatarUrl = selectedDigitalHuman.isEmpty
        ? null
        : _digitalHumanThumbnailUrl(selectedDigitalHuman);
    final status = task?['status']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 16, 16, 16),
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: studioBorder),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A111827),
            blurRadius: 24,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '实时预览',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
                ),
              ),
              _studioStatusPill(
                status.isEmpty ? '待生成' : _statusText(status),
                status == 'completed'
                    ? studioSuccess
                    : status == 'failed'
                        ? const Color(0xFFFF5D73)
                        : studioPrimary,
              ),
            ],
          ),
          const SizedBox(height: 4),
          const Text(
            '所有步骤的修改都会汇总到最终成片',
            style: TextStyle(color: studioMuted, fontSize: 11),
          ),
          const SizedBox(height: 14),
          Expanded(
            child: Center(
              child: AspectRatio(
                aspectRatio: 9 / 16,
                child: Container(
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    color: const Color(0xFF171925),
                    borderRadius: BorderRadius.circular(15),
                    border: Border.all(color: const Color(0xFF24283B)),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x26000000),
                        blurRadius: 20,
                        offset: Offset(0, 8),
                      ),
                    ],
                  ),
                  child: outputUrl != null
                      ? _OutputVideoPreview(url: outputUrl)
                      : avatarUrl != null
                          ? _digitalHumanPreviewImage(avatarUrl)
                          : sourceUrl != null
                              ? _OutputVideoPreview(url: sourceUrl)
                              : _previewPlaceholder(),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF7F8FC),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: studioBorder),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.smart_display_outlined,
                  color: studioPrimary,
                  size: 20,
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        outputUrl != null ? '成品视频已就绪' : '竖版视频 · 9:16',
                        style: const TextStyle(
                          color: studioInk,
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        outputUrl != null ? _cloudOutputLabel : '等待生成后可预览与下载',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style:
                            const TextStyle(color: studioMuted, fontSize: 10),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: '预览成品',
                  onPressed: outputUrl == null ? null : previewOutputVideo,
                  icon: const Icon(Icons.play_circle_outline_rounded),
                  color: studioPrimary,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _studioTip(String text) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F5FF),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: const Color(0xFFE1E2FF)),
      ),
      child: Row(
        children: [
          const Icon(Icons.lightbulb_outline_rounded,
              color: studioPrimary, size: 18),
          const SizedBox(width: 9),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: Color(0xFF5C6380),
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _studioFieldCard({
    required String title,
    required String subtitle,
    required IconData icon,
    required Widget child,
    Widget? trailing,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: studioBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: const Color(0xFFF1F2F7),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(icon, color: const Color(0xFF626A80), size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        color: studioInk,
                        fontSize: 14,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: studioMuted, fontSize: 10),
                    ),
                  ],
                ),
              ),
              if (trailing != null) trailing,
            ],
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }

  Widget _studioStatusPill(String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 10,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }

  Widget _studioSlider(
    String label,
    String subtitle,
    double value,
    double min,
    double max,
    ValueChanged<double> onChanged,
    String valueText,
  ) {
    return Row(
      children: [
        SizedBox(
          width: 90,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w900)),
              Text(subtitle,
                  style: const TextStyle(color: studioMuted, fontSize: 9)),
            ],
          ),
        ),
        Expanded(
          child: Slider(
            value: value,
            min: min,
            max: max,
            onChanged: onChanged,
          ),
        ),
        Container(
          width: 54,
          padding: const EdgeInsets.symmetric(vertical: 6),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: const Color(0xFFF4F5F8),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            valueText,
            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900),
          ),
        ),
      ],
    );
  }

  Widget _studioChoiceTile(String title, String subtitle, bool active) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 12),
      decoration: BoxDecoration(
        color: active ? const Color(0xFFF2F3FF) : const Color(0xFFF7F8FA),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(
          color: active ? const Color(0xFFC9CCFF) : studioBorder,
        ),
      ),
      child: Row(
        children: [
          Icon(
            active ? Icons.radio_button_checked : Icons.lock_outline_rounded,
            color: active ? studioPrimary : studioMuted,
            size: 19,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                        fontSize: 12, fontWeight: FontWeight.w900)),
                Text(subtitle,
                    style: const TextStyle(color: studioMuted, fontSize: 9)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _workspaceSidebar() {
    return Container(
      width: 228,
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(right: BorderSide(color: studioBorder)),
      ),
      child: SafeArea(
        child: Column(
          children: [
            SizedBox(
              height: 72,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: [studioPrimary, Color(0xFF7C5CFC)],
                      ),
                      borderRadius: BorderRadius.circular(11),
                      boxShadow: [
                        BoxShadow(
                          color: studioPrimary.withValues(alpha: 0.18),
                          blurRadius: 16,
                        ),
                      ],
                    ),
                    child: const Icon(Icons.play_arrow_rounded,
                        color: Colors.white, size: 26),
                  ),
                  const SizedBox(width: 10),
                  const Text(
                    '杰速口播',
                    style: TextStyle(
                      color: studioInk,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(child: _studioWorkflowRail(embedded: true)),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
              child: _sidebarItem(
                section: _WorkspaceSection.cloudAccount,
                icon: Icons.cloud_outlined,
                label: '云端账户',
                compact: false,
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 14),
              child: Tooltip(
                message: localApiOnline ? '本地服务 $apiBase' : '本地服务未连接，点击顶部刷新重试',
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: localApiOnline
                            ? const Color(0xFF51D8A5)
                            : const Color(0xFFFF6D8A),
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(localApiOnline ? '服务已连接' : '服务未连接',
                        style:
                            const TextStyle(color: studioMuted, fontSize: 12)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sidebarItem({
    required _WorkspaceSection section,
    required IconData icon,
    required String label,
    required bool compact,
  }) {
    final active = selectedSection == section;
    return Tooltip(
      message: compact ? label : '',
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () {
            setState(() => selectedSection = section);
            if (section == _WorkspaceSection.tasks) {
              loadTaskHistory(silent: true);
            } else if (section == _WorkspaceSection.accounts) {
              loadPublisherAccounts();
            }
          },
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            height: 48,
            padding: EdgeInsets.symmetric(horizontal: compact ? 0 : 13),
            decoration: BoxDecoration(
              color: active ? const Color(0xFFF0F1FF) : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: active ? const Color(0xFFD8DAFF) : Colors.transparent,
              ),
            ),
            child: Row(
              mainAxisAlignment:
                  compact ? MainAxisAlignment.center : MainAxisAlignment.start,
              children: [
                Icon(icon,
                    size: 20, color: active ? studioPrimary : studioMuted),
                if (!compact) ...[
                  const SizedBox(width: 12),
                  Text(
                    label,
                    style: TextStyle(
                      color: active ? studioPrimaryDark : studioInk,
                      fontWeight: active ? FontWeight.w800 : FontWeight.w600,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _workspaceTopBar() {
    return Container(
      height: 72,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: studioBorder)),
      ),
      child: Row(
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: _generationModeSelector(),
          ),
          const Spacer(),
          if (loading)
            const Padding(
              padding: EdgeInsets.only(right: 14),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => setState(
                () => selectedSection = _WorkspaceSection.cloudAccount),
            child: Container(
              height: 40,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                color: const Color(0xFFF7F8FC),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: studioBorder),
              ),
              child: Row(
                children: [
                  const CircleAvatar(
                    radius: 13,
                    backgroundColor: studioPrimary,
                    child: Icon(Icons.person, size: 16, color: Colors.white),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _cloudAccountBound
                        ? (_cloudUser?['email']?.toString() ?? '云端账户')
                        : '登录 / 注册',
                    style: const TextStyle(
                      color: studioInk,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 10),
          _topBarAction(Icons.refresh_rounded, '刷新数据', () async {
            await loadBootstrap();
            await loadTaskHistory(silent: true);
          }),
        ],
      ),
    );
  }

  Widget _topBarAction(IconData icon, String tooltip, VoidCallback onPressed) {
    return IconButton.filledTonal(
      tooltip: tooltip,
      onPressed: loading ? null : onPressed,
      icon: Icon(icon, size: 20),
      style: IconButton.styleFrom(
        backgroundColor: const Color(0xFFF1F2F7),
        foregroundColor: const Color(0xFF626A80),
      ),
    );
  }

  Widget _pageHeading(
    String title,
    String subtitle,
    IconData icon, {
    Widget? trailing,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: studioBorder),
      ),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [studioPrimary, Color(0xFF7C5CFC)],
              ),
              borderRadius: BorderRadius.circular(11),
            ),
            child: Icon(icon, color: Colors.white, size: 23),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                      color: studioInk,
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                    )),
                const SizedBox(height: 3),
                Text(subtitle,
                    style: const TextStyle(color: studioMuted, fontSize: 13)),
              ],
            ),
          ),
          if (trailing != null) trailing,
        ],
      ),
    );
  }

  Widget _voiceManagementPage() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _pageHeading(
            '声音管理',
            '上传授权声音、管理声音模型，并调整试听效果。',
            Icons.graphic_eq_rounded,
            trailing: _ghostButton('上传声音', uploadVoice),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '声音训练',
            subtitle: '建议上传 15–60 秒清晰人声，支持 MP3、WAV、M4A；最长不超过 5 分钟',
            icon: Icons.cloud_upload_outlined,
            child: Column(
              children: [
                _dropZone(
                  icon: Icons.multitrack_audio_rounded,
                  title: '上传声音参考文件',
                  subtitle: '建议无背景音乐、无混响、单人说话；15 秒以下也可以上传',
                  onTap: uploadVoice,
                ),
                const SizedBox(height: 12),
                _stepButton('上传并加入声音库', uploadVoice),
              ],
            ),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '我的声音库',
            subtitle: '点击卡片选择声音，系统声音与上传声音统一管理',
            icon: Icons.library_music_outlined,
            trailing: IconButton(
              tooltip: '刷新声音库',
              onPressed: loadBootstrap,
              icon: const Icon(Icons.refresh_rounded),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _labeledSlider(
                  '试听音量',
                  voicePreviewVolume,
                  0,
                  1,
                  _updateVoicePreviewVolume,
                  '${(voicePreviewVolume * 100).round()}%',
                ),
                const SizedBox(height: 8),
                _labeledSlider(
                  '试听语速',
                  speechRate,
                  0.6,
                  1.4,
                  (value) => setState(() => speechRate = value),
                  speechRate.toStringAsFixed(1),
                ),
                const SizedBox(height: 12),
                if (voices.isEmpty)
                  _emptyState('暂无声音模型', '点击“上传声音”添加第一条声音')
                else
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final voice in voices) _voiceLibraryCard(voice),
                    ],
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _voiceLibraryCard(Map<String, dynamic> voice) {
    final id = voice['voice_id']?.toString() ?? '';
    final selected = id == selectedVoice;
    final builtIn = voice['built_in'] == true;
    return SizedBox(
      width: 250,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(11),
          onTap: () => setState(() {
            selectedVoice = id;
            _invalidateGeneratedVoice();
          }),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: selected ? const Color(0xFF292247) : panelBg2,
              borderRadius: BorderRadius.circular(11),
              border: Border.all(
                  color: selected ? purpleLine : const Color(0xFF34374D)),
            ),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(colors: [cyan, pink]),
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: const Icon(Icons.volume_up_rounded, size: 20),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(voice['name']?.toString() ?? '未命名声音',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w800)),
                      const SizedBox(height: 3),
                      Text(builtIn ? '系统声音' : '我的声音',
                          style: const TextStyle(
                              color: Color(0x75FFFFFF), fontSize: 12)),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: selected && _isPlayingOriginalAudio ? '停止试听' : '试听',
                  onPressed: () => previewVoiceReference(id),
                  icon: Icon(
                    selected && _isPlayingOriginalAudio
                        ? Icons.stop_circle_outlined
                        : Icons.play_circle_outline_rounded,
                    size: 21,
                  ),
                ),
                if (!builtIn && voice['asset_id'] != null)
                  IconButton(
                    tooltip: '删除',
                    onPressed: () => _deleteAsset(voice['asset_id'].toString()),
                    icon: const Icon(Icons.delete_outline_rounded,
                        size: 20, color: Color(0xFFFF7892)),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _avatarManagementPage() {
    final customHumans =
        digitalHumans.where((item) => item['built_in'] != true).toList();
    return Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          _pageHeading(
            '形象管理',
            '管理数字人参考视频，选择后可回到创作中心生成口播视频。',
            Icons.smart_display_rounded,
            trailing: _ghostButton('上传形象', uploadDigitalHuman),
          ),
          const SizedBox(height: 14),
          Expanded(
            child: customHumans.isEmpty
                ? _managementCard(
                    title: '我的数字人',
                    subtitle: '尚未上传数字人参考视频',
                    icon: Icons.person_add_alt_1_rounded,
                    child: _dropZone(
                      icon: Icons.video_call_outlined,
                      title: '上传正面清晰的数字人参考视频',
                      subtitle: '建议人物面部无遮挡、光线稳定、口型自然',
                      onTap: uploadDigitalHuman,
                    ),
                  )
                : GridView.builder(
                    gridDelegate:
                        const SliverGridDelegateWithMaxCrossAxisExtent(
                      maxCrossAxisExtent: 320,
                      childAspectRatio: 0.78,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                    ),
                    itemCount: customHumans.length + 1,
                    itemBuilder: (context, index) {
                      if (index == 0) return _addAvatarCard();
                      return _avatarCard(customHumans[index - 1]);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _addAvatarCard() {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(13),
        onTap: uploadDigitalHuman,
        child: Container(
          decoration: BoxDecoration(
            color: panelBg,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(color: purpleLine.withValues(alpha: 0.5)),
          ),
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.add_circle_outline_rounded,
                  size: 48, color: Color(0xFFA98AFF)),
              SizedBox(height: 12),
              Text('上传新形象', style: TextStyle(fontWeight: FontWeight.w800)),
              SizedBox(height: 5),
              Text('MP4 / MOV / WebM',
                  style: TextStyle(color: Color(0x75FFFFFF), fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _avatarCard(Map<String, dynamic> human) {
    final id = human['digital_human_id']?.toString() ?? '';
    final selected = id == selectedDigitalHuman;
    final previewUrl = _digitalHumanThumbnailUrl(id);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(13),
        onTap: () => setState(() => selectedDigitalHuman = id),
        child: Container(
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: panelBg,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(
              color: selected ? pink : const Color(0xFF34374D),
              width: selected ? 1.5 : 1,
            ),
          ),
          child: Column(
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.network(
                      previewUrl,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => _previewPlaceholder(),
                    ),
                    if (selected)
                      const Positioned(
                        top: 10,
                        right: 10,
                        child: Chip(
                          avatar: Icon(Icons.check, size: 16),
                          label: Text('已选择'),
                          visualDensity: VisualDensity.compact,
                        ),
                      ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(11),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        human['name']?.toString() ?? '未命名形象',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    IconButton(
                      tooltip: '在创作中心使用',
                      onPressed: () => setState(() {
                        selectedDigitalHuman = id;
                        selectedSection = _WorkspaceSection.studio;
                      }),
                      icon: const Icon(Icons.movie_creation_outlined, size: 20),
                    ),
                    IconButton(
                      tooltip: '删除',
                      onPressed: () async {
                        setState(() => selectedDigitalHuman = id);
                        await deleteDigitalHuman();
                      },
                      icon: const Icon(Icons.delete_outline_rounded,
                          size: 20, color: Color(0xFFFF7892)),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _mediaManagementPage() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          _pageHeading(
            '素材管理',
            '集中管理背景音乐和画中画素材，选择后会自动带入当前创作任务。',
            Icons.folder_copy_rounded,
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ghostButton('上传 BGM', uploadBgm),
                const SizedBox(width: 8),
                _ghostButton('上传画中画', uploadPipAsset),
              ],
            ),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '背景音乐',
            subtitle: '选择、试听并调节用于视频合成的背景音乐',
            icon: Icons.music_note_rounded,
            trailing: SizedBox(
              width: 220,
              child: _labeledSlider(
                '音量',
                bgmVolume,
                0,
                1,
                _updateBgmVolume,
                '${(bgmVolume * 100).round()}%',
              ),
            ),
            child: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _bgmLibraryCard(
                  const {'bgm_id': 'none', 'name': '不使用背景音乐'},
                ),
                for (final track in bgmTracks) _bgmLibraryCard(track),
              ],
            ),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '画中画素材',
            subtitle: '上传图片或视频，在字幕编辑器中拖拽位置、大小和出现时间',
            icon: Icons.picture_in_picture_alt_rounded,
            child: LayoutBuilder(
              builder: (context, constraints) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: _dropZone(
                        icon: Icons.add_photo_alternate_outlined,
                        title:
                            pipAssetName.isEmpty ? '上传画中画图片或视频' : pipAssetName,
                        subtitle: pipAssetName.isEmpty
                            ? '支持常见图片与视频格式'
                            : '素材已关联当前任务，可继续设置显示方式',
                        onTap: uploadPipAsset,
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SwitchListTile.adaptive(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('启用画中画'),
                            subtitle: Text(_pipSummaryText),
                            value: pipEnabled,
                            onChanged: (value) =>
                                setState(() => pipEnabled = value),
                          ),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Expanded(
                                child: _dropdown(
                                  pipPosition,
                                  _pipPositionOptions,
                                  (value) =>
                                      _setPipPosition(value ?? pipPosition),
                                  labels: _pipPositionLabels,
                                ),
                              ),
                              const SizedBox(width: 8),
                              _stepButton(
                                '打开编辑预览',
                                editSubtitlesAndPip,
                                compact: true,
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _bgmLibraryCard(Map<String, dynamic> track) {
    final id = track['bgm_id']?.toString() ?? '';
    final selected = id == selectedBgm;
    final custom = track['built_in'] == false && track['asset_id'] != null;
    return SizedBox(
      width: 250,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(11),
          onTap: () => setState(() => selectedBgm = id),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: selected ? const Color(0xFF292247) : panelBg2,
              borderRadius: BorderRadius.circular(11),
              border: Border.all(
                  color: selected ? purpleLine : const Color(0xFF34374D)),
            ),
            child: Row(
              children: [
                Icon(id == 'none' ? Icons.music_off : Icons.music_note,
                    color: selected ? const Color(0xFFD7C4FF) : Colors.white54),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    track['name']?.toString() ?? '未命名音乐',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                if (id != 'none')
                  IconButton(
                    tooltip: '试听',
                    onPressed: () {
                      setState(() => selectedBgm = id);
                      playBgm();
                    },
                    icon: const Icon(Icons.play_circle_outline, size: 20),
                  ),
                if (custom)
                  IconButton(
                    tooltip: '删除',
                    onPressed: () => _deleteAsset(track['asset_id'].toString()),
                    icon: const Icon(Icons.delete_outline,
                        size: 19, color: Color(0xFFFF7892)),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _taskCenterPage() {
    final total = taskHistory.length;
    final filteredTasks = _filteredTaskHistory();
    final running = taskHistory
        .where((item) => {'created', 'imported', 'rendering'}
            .contains(item['status']?.toString()))
        .length;
    final completed = taskHistory
        .where((item) => item['status']?.toString() == 'completed')
        .length;
    final failed = taskHistory
        .where((item) => item['status']?.toString() == 'failed')
        .length;
    return Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          _pageHeading(
            '任务中心',
            '查看历史任务状态，打开任务继续编辑，或清理不再需要的本地文件。',
            Icons.format_list_bulleted_rounded,
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ghostButton('刷新', () => loadTaskHistory()),
                const SizedBox(width: 8),
                _stepButton(
                  '新建任务',
                  () => setState(
                      () => selectedSection = _WorkspaceSection.studio),
                  compact: true,
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                  child: _statCard('总任务', total, Icons.article_outlined, cyan)),
              const SizedBox(width: 10),
              Expanded(
                  child: _statCard('进行中', running, Icons.sync_rounded,
                      const Color(0xFFFFC857))),
              const SizedBox(width: 10),
              Expanded(
                  child: _statCard('已完成', completed, Icons.check_circle_outline,
                      const Color(0xFF51D8A5))),
              const SizedBox(width: 10),
              Expanded(
                  child: _statCard('失败', failed, Icons.error_outline,
                      const Color(0xFFFF6D8A))),
            ],
          ),
          const SizedBox(height: 14),
          Expanded(
            child: _managementCard(
              title: '任务列表',
              subtitle: loadingTaskHistory
                  ? '正在刷新任务...'
                  : '筛选结果 ${filteredTasks.length} 条 / 共 $total 条',
              icon: Icons.list_alt_rounded,
              expandChild: true,
              child: Column(
                children: [
                  _taskListToolbar(filteredTasks),
                  const Divider(height: 17),
                  Expanded(
                    child: filteredTasks.isEmpty
                        ? _emptyState(
                            taskHistory.isEmpty ? '暂无任务' : '没有符合条件的任务',
                            taskHistory.isEmpty
                                ? '前往创作中心导入视频，开始第一条口播创作'
                                : '请切换任务状态筛选条件',
                          )
                        : ListView.separated(
                            itemCount: filteredTasks.length,
                            separatorBuilder: (_, __) =>
                                const Divider(height: 1),
                            itemBuilder: (context, index) =>
                                _taskHistoryRow(filteredTasks[index]),
                          ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Map<String, dynamic>> _filteredTaskHistory() {
    if (taskStatusFilter == 'all') return taskHistory;
    final statuses = switch (taskStatusFilter) {
      'in_progress' => {'created', 'imported', 'rendering'},
      'editable' => {'transcribed', 'rewritten'},
      _ => {taskStatusFilter},
    };
    return taskHistory
        .where((item) => statuses.contains(item['status']?.toString() ?? ''))
        .toList(growable: false);
  }

  Widget _taskListToolbar(List<Map<String, dynamic>> filteredTasks) {
    const options = [
      'all',
      'in_progress',
      'editable',
      'created',
      'imported',
      'transcribed',
      'rewritten',
      'rendering',
      'completed',
      'failed',
    ];
    const labels = {
      'all': '全部状态',
      'in_progress': '进行中',
      'editable': '待继续编辑',
      'created': '已创建',
      'imported': '已导入',
      'transcribed': '已提取文案',
      'rewritten': '已完成仿写',
      'rendering': '视频生成中',
      'completed': '已完成',
      'failed': '失败',
    };
    final visibleIds = filteredTasks
        .map((item) => item['task_id']?.toString() ?? '')
        .where((id) => id.isNotEmpty)
        .toSet();
    final selectedVisible = visibleIds.where(selectedTaskIds.contains).length;
    final allSelected =
        visibleIds.isNotEmpty && selectedVisible == visibleIds.length;
    final checkboxValue = selectedVisible == 0
        ? false
        : allSelected
            ? true
            : null;
    return Row(
      children: [
        SizedBox(
          width: 190,
          child: _dropdown(
            taskStatusFilter,
            options,
            (value) =>
                setState(() => taskStatusFilter = value ?? taskStatusFilter),
            labels: labels,
          ),
        ),
        const SizedBox(width: 12),
        Checkbox(
          tristate: true,
          value: checkboxValue,
          onChanged: visibleIds.isEmpty
              ? null
              : (value) => setState(() {
                    if (value == true) {
                      selectedTaskIds.addAll(visibleIds);
                    } else {
                      selectedTaskIds.removeAll(visibleIds);
                    }
                  }),
        ),
        Text(
          allSelected ? '取消全选' : '全选当前结果',
          style: const TextStyle(color: Colors.white70),
        ),
        const SizedBox(width: 10),
        Text('已选 ${selectedTaskIds.length} 项',
            style: const TextStyle(color: Color(0xFFB99AFF))),
        const Spacer(),
        OutlinedButton.icon(
          onPressed: selectedTaskIds.isEmpty || batchDeletingTasks
              ? null
              : _deleteSelectedTasks,
          icon: batchDeletingTasks
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.delete_sweep_outlined),
          label: Text(batchDeletingTasks ? '删除中...' : '批量删除'),
          style: OutlinedButton.styleFrom(
            foregroundColor: const Color(0xFFFF7892),
            side: const BorderSide(color: Color(0xFF7A3C52)),
          ),
        ),
      ],
    );
  }

  Widget _statCard(String label, int value, IconData icon, Color color) {
    return Container(
      height: 88,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: panelBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF303348)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 12),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: Colors.white54)),
              Text('$value',
                  style: TextStyle(
                      color: color, fontSize: 24, fontWeight: FontWeight.w900)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _taskHistoryRow(Map<String, dynamic> item) {
    final status = item['status']?.toString() ?? '';
    final taskId = item['task_id']?.toString() ?? '';
    final outputReady = item['output_ready'] == true;
    return SizedBox(
      height: 66,
      child: Row(
        children: [
          Checkbox(
            value: selectedTaskIds.contains(taskId),
            onChanged: taskId.isEmpty
                ? null
                : (value) => setState(() {
                      if (value == true) {
                        selectedTaskIds.add(taskId);
                      } else {
                        selectedTaskIds.remove(taskId);
                      }
                    }),
          ),
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: _taskStatusColor(status).withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(_taskStatusIcon(status),
                size: 19, color: _taskStatusColor(status)),
          ),
          const SizedBox(width: 11),
          Expanded(
            flex: 4,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                    item['title']?.toString().isNotEmpty == true
                        ? item['title'].toString()
                        : '未命名视频任务',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w800)),
                const SizedBox(height: 3),
                Text(taskId,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style:
                        const TextStyle(color: Colors.white38, fontSize: 11)),
              ],
            ),
          ),
          Expanded(
            child: Text(_statusText(status),
                style: TextStyle(
                    color: _taskStatusColor(status),
                    fontWeight: FontWeight.w700)),
          ),
          SizedBox(
            width: 90,
            child: Text(outputReady ? '成品可用' : '暂无成品',
                style: TextStyle(
                    color: outputReady
                        ? const Color(0xFF51D8A5)
                        : Colors.white38)),
          ),
          _ghostButton('打开', () => _openTaskFromHistory(taskId)),
          const SizedBox(width: 7),
          IconButton(
            tooltip: '删除任务',
            onPressed: () => _deleteTaskFromHistory(item),
            icon: const Icon(Icons.delete_outline_rounded,
                color: Color(0xFFFF7892)),
          ),
        ],
      ),
    );
  }

  Color _taskStatusColor(String status) {
    return switch (status) {
      'completed' => const Color(0xFF51D8A5),
      'failed' => const Color(0xFFFF6D8A),
      'rendering' || 'imported' || 'created' => const Color(0xFFFFC857),
      _ => cyan,
    };
  }

  IconData _taskStatusIcon(String status) {
    return switch (status) {
      'completed' => Icons.check_rounded,
      'failed' => Icons.close_rounded,
      'rendering' || 'imported' || 'created' => Icons.sync_rounded,
      _ => Icons.edit_note_rounded,
    };
  }

  Widget _accountManagementPage() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          _pageHeading(
            '账号管理',
            '管理各平台发布账号的登录状态，发布时可直接选择已登录账号。',
            Icons.person_outline_rounded,
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ghostButton('刷新状态', loadPublisherAccounts),
                const SizedBox(width: 8),
                _stepButton('添加账号', _showAddPublisherAccountDialog,
                    compact: true),
              ],
            ),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '发布账号',
            subtitle: '支持抖音、快手、小红书和视频号',
            icon: Icons.account_circle_outlined,
            child: publisherAccounts.isEmpty
                ? _emptyState('还没有发布账号', '点击“添加账号”，再完成平台登录')
                : Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      for (final account in publisherAccounts)
                        _publisherAccountCard(account),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _cloudAccountPage() {
    final wallet = cloudWallet ?? const <String, dynamic>{};
    final available = wallet['available_points'] ?? 0;
    final frozen = wallet['frozen_points'] ?? 0;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          _pageHeading(
            '云端账户',
            '管理云端登录、软件授权、点数余额和任务扣点明细。',
            Icons.cloud_outlined,
            trailing: _ghostButton('刷新账户', () async {
              await loadCloudMe(silent: true);
              await loadCloudLedger(silent: true);
            }),
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '账户信息',
            subtitle: '用于云端文案提取、声音克隆和视频生成',
            icon: Icons.account_circle_outlined,
            child: _accountModule(),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _cloudMetricCard(
                  '可用点数',
                  '$available 点',
                  Icons.toll_rounded,
                  const Color(0xFF51D8A5),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _cloudMetricCard(
                  '冻结点数',
                  '$frozen 点',
                  Icons.lock_clock_outlined,
                  const Color(0xFFFFC857),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _cloudMetricCard(
                  '软件授权',
                  _cloudLicensed ? '已激活' : '未激活',
                  Icons.verified_user_outlined,
                  _cloudLicensed
                      ? const Color(0xFF51D8A5)
                      : const Color(0xFFFF6D8A),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _managementCard(
            title: '最近点数明细',
            subtitle: cloudLedger.isEmpty ? '暂无扣点记录' : '展示最近的账户变动',
            icon: Icons.receipt_long_outlined,
            child: cloudLedger.isEmpty
                ? _emptyState('暂无点数明细', '完成云端任务后会在这里显示扣点记录')
                : Column(
                    children: [
                      for (final item in cloudLedger.take(12))
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          child: Row(
                            children: [
                              const Icon(Icons.bolt_rounded,
                                  size: 18, color: Color(0xFFB99AFF)),
                              const SizedBox(width: 9),
                              Expanded(
                                child: Text(
                                  _ledgerTitle(item),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w700),
                                ),
                              ),
                              Text(
                                item['points']?.toString() ??
                                    item['amount']?.toString() ??
                                    '',
                                style: const TextStyle(
                                    color: Color(0xFFFFC857),
                                    fontWeight: FontWeight.w800),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _cloudMetricCard(
      String label, String value, IconData icon, Color color) {
    return Container(
      height: 92,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: panelBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF303348)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 12),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: Colors.white54)),
              const SizedBox(height: 3),
              Text(value,
                  style: TextStyle(
                      color: color, fontSize: 21, fontWeight: FontWeight.w900)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _publisherAccountCard(Map<String, dynamic> account) {
    final id = account['account_id']?.toString() ?? '';
    final platform = account['platform']?.toString() ?? '';
    final status = account['status']?.toString() ?? '';
    final loggedIn = status == 'logged_in';
    return SizedBox(
      width: 340,
      child: Container(
        padding: const EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: panelBg2,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: loggedIn
                ? const Color(0xFF51D8A5).withValues(alpha: 0.55)
                : const Color(0xFF3A3D54),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: _platformColor(platform).withValues(alpha: 0.16),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(_platformLabel(platform),
                      style: TextStyle(
                          color: _platformColor(platform),
                          fontWeight: FontWeight.w800,
                          fontSize: 12)),
                ),
                const Spacer(),
                Icon(loggedIn ? Icons.check_circle : Icons.info_outline,
                    size: 18,
                    color: loggedIn
                        ? const Color(0xFF51D8A5)
                        : const Color(0xFFFFC857)),
              ],
            ),
            const SizedBox(height: 13),
            Text(_accountDisplayName(account),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style:
                    const TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
            const SizedBox(height: 5),
            Text(_accountStatusLabel(status),
                style: const TextStyle(color: Colors.white54)),
            const SizedBox(height: 13),
            Row(
              children: [
                Expanded(
                  child: _ghostButton(
                    loggedIn ? '重新登录' : '登录',
                    () => _runPublisherAccountAction(id, loginPublisherAccount),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _ghostButton(
                    '检测状态',
                    () => _runPublisherAccountAction(id, checkPublisherSession),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  tooltip: '在创作中心使用',
                  onPressed: () => setState(() {
                    selectedPublishPlatform = platform;
                    selectedPublisherAccount = id;
                    selectedSection = _WorkspaceSection.studio;
                  }),
                  icon: const Icon(Icons.arrow_forward_rounded),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Color _platformColor(String platform) {
    return switch (platform) {
      'douyin' => const Color(0xFFFF5470),
      'kuaishou' => const Color(0xFFFF8A4C),
      'xiaohongshu' => const Color(0xFFFF4563),
      'shipinhao' => const Color(0xFF51D8A5),
      _ => cyan,
    };
  }

  Future<void> _runPublisherAccountAction(
    String accountId,
    Future<void> Function() action,
  ) async {
    setState(() {
      selectedPublisherAccount = accountId;
      final account = publisherAccounts.firstWhere(
        (item) => item['account_id'] == accountId,
        orElse: () => const {},
      );
      if (account.isNotEmpty) {
        selectedPublishPlatform = account['platform']?.toString() ?? 'douyin';
      }
    });
    await action();
  }

  Future<void> _showAddPublisherAccountDialog() async {
    final nicknameController = TextEditingController();
    var platform = selectedPublishPlatform;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('添加发布账号'),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('平台类型'),
                const SizedBox(height: 7),
                DropdownButtonFormField<String>(
                  initialValue: platform,
                  decoration: _inputDecoration(''),
                  items:
                      const ['douyin', 'kuaishou', 'xiaohongshu', 'shipinhao']
                          .map((value) => DropdownMenuItem(
                                value: value,
                                child: Text(_platformLabel(value)),
                              ))
                          .toList(),
                  onChanged: (value) =>
                      setDialogState(() => platform = value ?? platform),
                ),
                const SizedBox(height: 12),
                const Text('显示名称（可选）'),
                const SizedBox(height: 7),
                TextField(
                  controller: nicknameController,
                  decoration: _inputDecoration('登录后可自动识别'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('添加'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true) {
      nicknameController.dispose();
      return;
    }
    setState(() {
      selectedPublishPlatform = platform;
      publisherNicknameController.text = nicknameController.text.trim();
    });
    nicknameController.dispose();
    await createPublisherAccount();
  }

  Widget _managementCard({
    required String title,
    required String subtitle,
    required IconData icon,
    required Widget child,
    Widget? trailing,
    bool expandChild = false,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: panelBg,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: const Color(0xFF303348)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 21, color: const Color(0xFFB99AFF)),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: const TextStyle(
                            fontSize: 17, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 2),
                    Text(subtitle,
                        style: const TextStyle(
                            color: Color(0x75FFFFFF), fontSize: 12)),
                  ],
                ),
              ),
              if (trailing != null) trailing,
            ],
          ),
          const SizedBox(height: 14),
          if (expandChild) Expanded(child: child) else child,
        ],
      ),
    );
  }

  Widget _dropZone({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(11),
        onTap: loading ? null : onTap,
        child: Container(
          width: double.infinity,
          constraints: const BoxConstraints(minHeight: 160),
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: const Color(0xFF151724),
            borderRadius: BorderRadius.circular(11),
            border: Border.all(
              color: purpleLine.withValues(alpha: 0.65),
              style: BorderStyle.solid,
            ),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 36, color: const Color(0xFFC4A9FF)),
              const SizedBox(height: 10),
              Text(title,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 5),
              Text(subtitle,
                  textAlign: TextAlign.center,
                  style:
                      const TextStyle(color: Color(0x75FFFFFF), fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _emptyState(String title, String subtitle) {
    return SizedBox(
      height: 180,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.inbox_outlined, size: 40, color: Colors.white30),
            const SizedBox(height: 9),
            Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(subtitle,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white38, fontSize: 12)),
          ],
        ),
      ),
    );
  }

  Future<void> _deleteAsset(String assetId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删除素材'),
        content: const Text('确定删除这个自定义素材吗？已生成的视频不会受影响。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _runBusy(() async {
      final res = await http.delete(Uri.parse('$apiBase/api/assets/$assetId'));
      _check(res);
      await loadBootstrap();
      showInfo('素材已删除');
    });
  }

  Widget _gateScaffold(String title, {bool showActivationActions = false}) {
    return Scaffold(
      body: Column(
        children: [
          _banner(showAccount: false),
          Expanded(
            child: Center(
              child: Container(
                width: showActivationActions ? 520 : 420,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: panelBg,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: purpleLine.withValues(alpha: 0.5)),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.lock_outline,
                      size: 38,
                      color: Color(0xFFA86CFF),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      showActivationActions
                          ? '必须先完成软件激活，激活成功后才能进入主界面登录或注册。'
                          : '激活完成后才能进入主界面',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white70),
                    ),
                    if (showActivationActions) ...[
                      const SizedBox(height: 18),
                      Row(
                        children: [
                          Expanded(
                            child: _input(
                              cloudActivationCodeController,
                              '输入软件激活码',
                            ),
                          ),
                          const SizedBox(width: 10),
                          FilledButton.icon(
                            onPressed:
                                loading ? null : _activateSoftwareFromInput,
                            icon: const Icon(Icons.verified_user_outlined),
                            label: const Text('激活软件'),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
          if (message.isNotEmpty) _messageBar(),
        ],
      ),
    );
  }

  Widget _banner({bool showAccount = true}) {
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
            '杰口播智能体',
            style: TextStyle(fontSize: 21, fontWeight: FontWeight.w900),
          ),
          if (showAccount) ...[
            const SizedBox(width: 26),
            Expanded(
              child: Align(
                alignment: Alignment.center,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 620),
                  child: _generationModeSelector(),
                ),
              ),
            ),
            const SizedBox(width: 18),
          ] else
            const Spacer(),
          if (showAccount) _accountModule(),
        ],
      ),
    );
  }

  // ignore: unused_element
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

  Widget _generationModeSelector() {
    final isCloud = generationMode == 'cloud';
    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F8FC),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: studioBorder),
      ),
      child: Row(
        children: [
          const Text(
            '运行模式',
            style: TextStyle(
              color: studioInk,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(width: 10),
          _modeSelectChip(
            '本地生成',
            Icons.radio_button_unchecked,
            false,
            null,
            enabled: false,
          ),
          const SizedBox(width: 8),
          _modeSelectChip(
            '云端生成',
            Icons.check_circle_rounded,
            isCloud,
            () => setState(() => generationMode = 'cloud'),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              '云端生成将按账号点数扣费',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: studioMuted,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _modeSelectChip(
    String label,
    IconData icon,
    bool active,
    VoidCallback? onTap, {
    bool enabled = true,
  }) {
    final canTap = enabled && !loading && onTap != null;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: canTap ? onTap : null,
      child: Container(
        height: 36,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: active
              ? const Color(0xFFEEF0FF)
              : enabled
                  ? Colors.white
                  : const Color(0xFFF0F1F4),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: active
                ? const Color(0xFFC9CCFF)
                : enabled
                    ? studioBorder
                    : const Color(0xFFE4E6EB),
            width: active ? 1.4 : 1,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 16,
              color: active
                  ? studioPrimary
                  : enabled
                      ? studioMuted
                      : const Color(0xFFB4B8C3),
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color: enabled ? studioInk : const Color(0xFFA7ABB6),
                fontWeight: FontWeight.w900,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // Legacy three-column layout kept as a fallback while the new workflow UI
  // reuses its lower-level controls.
  // ignore: unused_element
  Widget _leftPanel() {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(10, 10, 5, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionTitle('1. 提取视频文案'),
                _input(urlController, '粘贴抖音分享链接或完整分享文案'),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(child: _stepButton('提取文案', createTask)),
                    const SizedBox(width: 8),
                    _ghostButton('选择视频', uploadSourceVideo),
                  ],
                ),
                const SizedBox(height: 8),
                _textBox(originalScriptController, '提取的原文案', 8),
              ],
            ),
          ),
          const SizedBox(height: 10),
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionTitle('2. 一键仿写'),
                _styleDropdown(),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(child: _input(audienceController, '目标人群')),
                    const SizedBox(width: 8),
                    Expanded(child: _input(productController, '产品/服务')),
                  ],
                ),
                const SizedBox(height: 8),
                _stepButton('生成改写文案', rewrite),
                const SizedBox(height: 8),
                _textBox(rewrittenScriptController, '改写后的文案', 15),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _digitalHumanRenderPanel() {
    final userDigitalHumans =
        digitalHumans.where((item) => item['built_in'] != true).toList();
    final humanOptions = _limitedProfileOptions(
        userDigitalHumans, 'digital_human_id',
        preferredSystemPrefix: 'custom:');
    if (humanOptions.isEmpty) {
      humanOptions.add('');
    }
    final humanLabels = {
      '': '未选择数字人视频',
      for (final h in userDigitalHumans)
        h['digital_human_id'] as String: h['name'] as String,
    };

    return _panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionHeader('5. 数字人生成成品视频', '视频服务：', '已启动'),
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
          Row(
            children: [
              const SizedBox(
                width: 70,
                child: Text(
                  '数字人',
                  style: TextStyle(
                    color: Colors.white70,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const Spacer(),
              _ghostButton('上传形象', uploadDigitalHuman),
              const SizedBox(width: 8),
              _ghostButton('删除', deleteDigitalHuman),
              const SizedBox(width: 8),
              _stepButton(
                renderingVideo ? '停止生成' : '生成成品视频',
                renderingVideo ? stopRender : render,
                compact: true,
                allowWhileLoading: renderingVideo,
              ),
            ],
          ),
          const SizedBox(height: 10),
          _digitalHumanPicker(humanOptions, humanLabels),
          const SizedBox(height: 8),
          _stepButton(
            renderingVideo ? '停止生成' : '5. 一键生成成品视频',
            renderingVideo ? stopRender : render,
            allowWhileLoading: renderingVideo,
          ),
        ],
      ),
    );
  }

  // ignore: unused_element
  Widget _centerPanel() {
    final voiceOptions = _limitedProfileOptions(voices, 'voice_id',
        preferredSystemPrefix: 'clone:');
    final voiceLabels = {
      for (final v in voices) v['voice_id'] as String: v['name'] as String,
    };

    return SingleChildScrollView(
      padding: const EdgeInsets.all(10),
      child: Column(
        children: [
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeader('3. 声音生成', '声音服务：', _voiceServiceText),
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
                _labeledSlider(
                  '音量',
                  voicePreviewVolume,
                  0,
                  1,
                  _updateVoicePreviewVolume,
                  '${(voicePreviewVolume * 100).round()}%',
                ),
                const SizedBox(height: 10),
                const Text('声音',
                    style: TextStyle(
                        color: Colors.white70, fontWeight: FontWeight.w800)),
                const SizedBox(height: 7),
                ConstrainedBox(
                  constraints: const BoxConstraints(minWidth: 180),
                  child: _dropdown(
                    selectedVoice,
                    voiceOptions,
                    (v) => setState(() {
                      selectedVoice = v ?? selectedVoice;
                      _invalidateGeneratedVoice();
                    }),
                    labels: voiceLabels,
                  ),
                ),
                const SizedBox(height: 9),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _ghostButton('上传声音', uploadVoice),
                    _stepButton(
                      _cloudVoiceJobActive ? '停止克隆' : '克隆声音',
                      _cloudVoiceJobActive ? stopCloudVoiceJob : cloneVoice,
                      compact: true,
                      allowWhileLoading: _cloudVoiceJobActive,
                    ),
                    _stepButton(
                      _isPlayingVoice ? '停止播放' : '播放声音',
                      playVoice,
                      compact: true,
                    ),
                    _stepButton(
                      _isPlayingOriginalAudio ? '原音停止' : '原音播放',
                      playOriginalAudio,
                      compact: true,
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          _panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionHeader('4. 字幕/BGM/画中画设置', '合成参数：', '生成前生效'),
                const SizedBox(height: 10),
                _subTabs(),
                const SizedBox(height: 10),
                _mediaSubTabPanel(),
              ],
            ),
          ),
          const SizedBox(height: 10),
          _digitalHumanRenderPanel(),
        ],
      ),
    );
  }

  // ignore: unused_element
  Widget _rightPanel() {
    final sourceUrl = _sourceVideoUrl;
    final outputUrl = _outputVideoUrl;
    final digitalHumanPreviewUrl = selectedDigitalHuman.isEmpty
        ? null
        : _digitalHumanThumbnailUrl(selectedDigitalHuman);
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
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (outputUrl != null)
                    _OutputVideoPreview(url: outputUrl)
                  else if (digitalHumanPreviewUrl != null)
                    _digitalHumanPreviewImage(digitalHumanPreviewUrl)
                  else if (sourceUrl != null)
                    _OutputVideoPreview(url: sourceUrl)
                  else
                    _previewPlaceholder(),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          _outputFileBar(),
          const SizedBox(height: 12),
          _sectionTitle('6. 视频封面'),
          const SizedBox(height: 8),
          _coverTools(),
          const SizedBox(height: 8),
          _coverPreview(),
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
    final isCloud = generationMode == 'cloud';
    final path = _outputVideoPath;
    final fileName = isCloud
        ? _cloudOutputLabel
        : path == null || path.isEmpty
            ? '成品视频生成后自动关联'
            : path.split(RegExp(r'[\\/]')).last;
    return Row(
      children: [
        Expanded(child: _readonlyBox(fileName)),
        const SizedBox(width: 8),
        _ghostButton('打开', openOutputVideo),
        const SizedBox(width: 8),
        _ghostButton('预览', previewOutputVideo),
        if (isCloud &&
            cloudOutputUrl.isNotEmpty &&
            cloudOutputLocalPath.isEmpty) ...[
          const SizedBox(width: 8),
          _ghostButton('确认下载', () => confirmCloudDownload()),
        ],
      ],
    );
  }

  Widget _coverTools() {
    return Row(
      children: [
        const Icon(Icons.image_outlined, size: 18),
        const SizedBox(width: 6),
        const Expanded(
          child: Text('封面', style: TextStyle(fontWeight: FontWeight.w800)),
        ),
        _ghostButton('生成封面', generateCover),
        const SizedBox(width: 8),
        _ghostButton('自定义封面', uploadCover),
      ],
    );
  }

  Widget _coverPreview() {
    final light = _studioLightControls;
    final path = _currentCoverPath;
    final label = path == null ? '封面将自动生成' : _fileNameFromPath(path);
    return Column(
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: SizedBox(
            height: 220,
            child: AspectRatio(
              aspectRatio: 9 / 16,
              child: Container(
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  color:
                      light ? const Color(0xFFF0F2F6) : const Color(0xFF25283A),
                  borderRadius: BorderRadius.circular(light ? 12 : 8),
                  border: Border.all(
                    color: light
                        ? studioBorder
                        : purpleLine.withValues(alpha: 0.5),
                  ),
                ),
                child: path == null
                    ? Center(
                        child: Icon(
                          Icons.image_outlined,
                          color: light ? studioMuted : Colors.white54,
                        ),
                      )
                    : Image.file(
                        File(path),
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => Center(
                          child: Icon(
                            Icons.broken_image,
                            color: light ? studioMuted : Colors.white70,
                          ),
                        ),
                      ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        _readonlyBox(label),
      ],
    );
  }

  String? get _currentCoverPath {
    if (coverPath.isNotEmpty && File(coverPath).existsSync()) return coverPath;
    final taskCover = task?['cover_path'] as String?;
    if (taskCover != null &&
        taskCover.isNotEmpty &&
        File(taskCover).existsSync()) {
      return taskCover;
    }
    return null;
  }

  Widget _publisherPanel() {
    final light = _studioLightControls;
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
                  '发布设置',
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
                      ? _publisherNicknamePlaceholder
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
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: light ? const Color(0xFFF8F7FF) : const Color(0xFF34223C),
              borderRadius: BorderRadius.circular(light ? 12 : 8),
              border: Border.all(
                color: light
                    ? const Color(0xFFE2E0FF)
                    : pink.withValues(alpha: 0.55),
              ),
            ),
            child: Column(
              children: [
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
                _input(publishTopicsController, '话题标签，用 # 分隔'),
                const SizedBox(height: 8),
                _stepButton(
                  publishing ? '发布任务创建中...' : '创建发布任务',
                  createPublishJobs,
                  allowWhileLoading: publishing,
                ),
              ],
            ),
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
          child: _publishModeChip('draft', '保存草稿', Icons.edit_note_outlined),
        ),
      ],
    );
  }

  Widget _publishModeChip(String value, String label, IconData icon) {
    final light = _studioLightControls;
    final active = selectedPublishMode == value;
    return InkWell(
      onTap: () => setState(() => selectedPublishMode = value),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 42,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active
              ? light
                  ? const Color(0xFFEEF0FF)
                  : const Color(0xFF25315A)
              : light
                  ? Colors.white
                  : panelBg2,
          borderRadius: BorderRadius.circular(light ? 10 : 8),
          border: Border.all(
            color: active
                ? light
                    ? studioPrimary
                    : cyan
                : light
                    ? studioBorder
                    : purpleLine.withValues(alpha: 0.45),
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 17,
              color: active
                  ? light
                      ? studioPrimary
                      : cyan
                  : light
                      ? studioMuted
                      : Colors.white54,
            ),
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
      'login_opened' => '登录窗口已打开',
      'logged_in' => '已登录',
      'needs_login' => '待登录',
      'needs_user_action' => '需要人工处理',
      'expired' => '已过期',
      'failed' => '失败',
      _ => status,
    };
  }

  String _accountDisplayName(Map<String, dynamic> account) {
    final nickname = _normalizedPublisherNickname(account['nickname']);
    if (nickname.isNotEmpty) return nickname;
    return _publisherNicknamePlaceholder;
  }

  String _normalizedPublisherNickname(Object? value) {
    final nickname = value is String ? value.trim() : '';
    if (nickname.isEmpty) return '';
    final compact = nickname.replaceAll(RegExp(r'\s+'), '');
    final blockedParts = [
      '草稿箱',
      '上传视频',
      '上传图文',
      '写长文',
      '发播客',
      '拖拽视频',
      '视频大小',
      '视频格式',
      '视频分辨率',
      '收起侧边栏',
      'Builderhub',
      'RedSkill',
    ];
    if (blockedParts.any(compact.contains)) return '';
    return nickname;
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
    final light = _studioLightControls;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: light ? Colors.white : panelBg,
        borderRadius: BorderRadius.circular(light ? 14 : 10),
        border: Border.all(
          color: light ? studioBorder : purpleLine.withValues(alpha: 0.35),
        ),
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

  List<String> _limitedProfileOptions(
    List<Map<String, dynamic>> items,
    String idKey, {
    String? preferredSystemPrefix,
  }) {
    final preferredSystemOptions = <String>[];
    final fallbackSystemOptions = <String>[];
    final seenSystem = <String>{};
    final userOptions = <MapEntry<int, Map<String, dynamic>>>[];
    final seenUser = <String>{};

    for (var i = 0; i < items.length; i++) {
      final item = items[i];
      final id = item[idKey]?.toString() ?? '';
      if (id.isEmpty) continue;
      final builtIn = item['built_in'] == true;
      if (builtIn) {
        if (seenSystem.add(id)) {
          if (preferredSystemPrefix != null &&
              id.startsWith(preferredSystemPrefix)) {
            preferredSystemOptions.add(id);
          } else {
            fallbackSystemOptions.add(id);
          }
        }
        continue;
      }
      if (seenUser.add(id)) {
        userOptions.add(MapEntry(i, item));
      }
    }

    userOptions.sort((a, b) {
      final aUsedAt = a.value['last_used_at']?.toString() ?? '';
      final bUsedAt = b.value['last_used_at']?.toString() ?? '';
      if (aUsedAt.isNotEmpty || bUsedAt.isNotEmpty) {
        return bUsedAt.compareTo(aUsedAt);
      }
      return a.key.compareTo(b.key);
    });

    final systemOptions = (preferredSystemOptions.isNotEmpty
            ? preferredSystemOptions
            : fallbackSystemOptions)
        .take(4);

    return [
      ...systemOptions,
      ...userOptions
          .take(10)
          .map((entry) => entry.value[idKey]?.toString() ?? '')
          .where((id) => id.isNotEmpty),
    ];
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
    final light = _studioLightControls;
    return InputDecoration(
      hintText: hint.isEmpty ? null : hint,
      filled: true,
      fillColor: light ? const Color(0xFFF8F9FC) : panelBg2,
      hintStyle: light ? const TextStyle(color: Color(0xFFA1A7B7)) : null,
      isDense: true,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(light ? 10 : 7),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(light ? 10 : 7),
        borderSide: BorderSide(
          color: light ? studioBorder : purpleLine.withValues(alpha: 0.45),
        ),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(light ? 10 : 7),
        borderSide: BorderSide(
          color: light ? studioPrimary : cyan,
          width: 1.2,
        ),
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
    final light = _studioLightControls;
    final child = DecoratedBox(
      decoration: BoxDecoration(
        gradient: disabled || light
            ? null
            : const LinearGradient(colors: [cyan, pink]),
        color: disabled
            ? (light ? const Color(0xFFE3E5EB) : Colors.white12)
            : light
                ? studioPrimary
                : null,
        borderRadius: BorderRadius.circular(light ? 10 : 8),
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
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(light ? 10 : 8),
          ),
        ),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w900)),
      ),
    );
    return compact ? child : SizedBox(width: double.infinity, child: child);
  }

  Widget _ghostButton(String text, VoidCallback onPressed) {
    final light = _studioLightControls;
    return OutlinedButton(
      onPressed: loading ? null : onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: light ? studioInk : Colors.white,
        side: BorderSide(
          color: light
              ? const Color(0xFFD9DCE5)
              : purpleLine.withValues(alpha: 0.8),
        ),
        backgroundColor: light ? Colors.white : panelBg2,
        minimumSize: const Size(72, 40),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(light ? 10 : 8),
        ),
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
    final light = _studioLightControls;
    return Container(
      height: 42,
      alignment: Alignment.centerLeft,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: light ? const Color(0xFFF8F9FC) : panelBg2,
        borderRadius: BorderRadius.circular(light ? 10 : 7),
        border: Border.all(
          color: light ? studioBorder : purpleLine.withValues(alpha: 0.4),
        ),
      ),
      child: Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: light ? const TextStyle(color: studioMuted) : null,
      ),
    );
  }

  Map<String, dynamic>? _digitalHumanProfile(String digitalHumanId) {
    for (final item in digitalHumans) {
      if (item['digital_human_id'] == digitalHumanId) return item;
    }
    return null;
  }

  String _digitalHumanThumbnailUrl(String digitalHumanId) {
    final profile = _digitalHumanProfile(digitalHumanId);
    final providedUrl = profile?['thumbnail_url']?.toString() ?? '';
    if (providedUrl.isNotEmpty) {
      if (providedUrl.startsWith('http://') ||
          providedUrl.startsWith('https://')) {
        return providedUrl;
      }
      return '$apiBase$providedUrl';
    }
    final version = profile?['last_used_at']?.toString() ??
        profile?['asset_id']?.toString();
    return Uri.parse('$apiBase/api/digital-humans/thumbnail').replace(
      queryParameters: {
        'digital_human_id': digitalHumanId,
        if (version != null && version.isNotEmpty) 'v': version,
      },
    ).toString();
  }

  Widget _digitalHumanPicker(
    List<String> options,
    Map<String, String> labels,
  ) {
    final light = _studioLightControls;
    final visibleOptions = options.where((id) => id.isNotEmpty).toList();
    if (visibleOptions.isEmpty) {
      return _readonlyBox('请上传或选择数字人素材');
    }
    final visibleRows = math.min(4, math.max(1, visibleOptions.length));
    final dividerHeight = math.max(0, visibleRows - 1).toDouble();
    return Container(
      height: 72.0 * visibleRows + dividerHeight,
      decoration: BoxDecoration(
        color: light ? const Color(0xFFF8F9FC) : const Color(0xFF171A28),
        borderRadius: BorderRadius.circular(light ? 11 : 8),
        border: Border.all(
          color: light ? studioBorder : purpleLine.withValues(alpha: 0.45),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: ListView.separated(
        padding: EdgeInsets.zero,
        itemCount: visibleOptions.length,
        itemBuilder: (context, index) {
          final id = visibleOptions[index];
          return _digitalHumanRow(id, labels[id] ?? id);
        },
        separatorBuilder: (_, __) => Divider(
          height: 1,
          color: light ? studioBorder : Colors.white.withValues(alpha: 0.08),
        ),
      ),
    );
  }

  Widget _digitalHumanRow(String digitalHumanId, String name) {
    final light = _studioLightControls;
    final active = selectedDigitalHuman == digitalHumanId;
    final profile = _digitalHumanProfile(digitalHumanId);
    final builtIn = profile?['built_in'] == true;
    return InkWell(
      onTap: () => selectDigitalHuman(digitalHumanId),
      child: Container(
        height: 72,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: active
              ? light
                  ? const Color(0xFFEEF0FF)
                  : const Color(0xFF262B47)
              : Colors.transparent,
          border: Border(
            left: BorderSide(
              color: active
                  ? light
                      ? studioPrimary
                      : cyan
                  : Colors.transparent,
              width: 3,
            ),
          ),
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: SizedBox(
                width: 54,
                height: 48,
                child: Image.network(
                  _digitalHumanThumbnailUrl(digitalHumanId),
                  key: ValueKey(_digitalHumanThumbnailUrl(digitalHumanId)),
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Container(
                    color: light
                        ? const Color(0xFFEDEFF4)
                        : const Color(0xFF24283A),
                    child: Icon(
                      Icons.person,
                      color: light ? studioMuted : Colors.white54,
                      size: 24,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    builtIn ? '系统模板' : '已上传形象',
                    style: TextStyle(
                      color: builtIn
                          ? light
                              ? studioPrimary
                              : const Color(0xFFBFA8FF)
                          : light
                              ? studioSuccess
                              : const Color(0xFF55E6A5),
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            if (active)
              Icon(
                Icons.check_circle,
                size: 18,
                color: light ? studioPrimary : const Color(0xFF55E6A5),
              ),
          ],
        ),
      ),
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
    final options = _effectiveBgmOptions();
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
            const SizedBox(width: 8),
            _ghostButton(_isPlayingBgm ? '停止BGM' : '播放BGM', playBgm),
          ],
        ),
        if (selectedBgm != 'none') ...[
          const SizedBox(height: 10),
          _labeledSlider(
            'BGM音量',
            bgmVolume,
            0,
            0.6,
            _updateBgmVolume,
            '${(bgmVolume * 100).round()}%',
          ),
        ],
        const SizedBox(height: 4),
        Text(
          selectedBgm == 'none'
              ? '最终视频不会混入背景音乐。'
              : selectedBgm.startsWith('custom:')
                  ? '将使用你上传的背景音乐，并按音量混入最终视频。'
                  : '将使用模板背景音乐，并按音量混入最终视频。',
          style: TextStyle(
            color: _studioLightControls ? studioMuted : Colors.white60,
            fontSize: 12,
          ),
        ),
      ],
    );
  }

  List<String> _effectiveBgmOptions() {
    return _effectiveBgmOptionsFor(bgmTracks);
  }

  List<String> _effectiveBgmOptionsFor(List<Map<String, dynamic>> tracks) {
    final templateIds = <String>[];
    final fallbackIds = <String>[];
    final customIds = <String>[];
    final seen = <String>{'none'};
    for (final item in tracks) {
      final id = item['bgm_id']?.toString() ?? '';
      if (id.isEmpty || !seen.add(id)) continue;
      if (id.startsWith('template:')) {
        templateIds.add(id);
      } else if (id.startsWith('custom:')) {
        customIds.add(id);
      } else {
        fallbackIds.add(id);
      }
    }
    return [
      'none',
      ...(templateIds.isNotEmpty ? templateIds : fallbackIds),
      ...customIds.take(10),
    ];
  }

  Widget _subtitlePanel() {
    final subtitleSummary = subtitlePreviewLines.isEmpty
        ? '字幕文件将自动生成'
        : subtitlePreviewLines.take(2).join(' / ');
    return Column(
      children: [
        Row(
          children: [
            Expanded(child: _readonlyBox(subtitleSummary)),
            const SizedBox(width: 8),
            _stepButton('生成字幕', generateSubtitles, compact: true),
            const SizedBox(width: 8),
            _ghostButton('编辑字幕及画中画', editSubtitlesAndPip),
          ],
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 116,
              child: Row(
                children: [
                  Checkbox(
                    value: subtitlesEnabled,
                    onChanged: (value) => setState(
                      () => subtitlesEnabled = value ?? subtitlesEnabled,
                    ),
                  ),
                  const Text('启用字幕'),
                ],
              ),
            ),
            SizedBox(
              width: 210,
              child: _dropdown(
                selectedSubtitleFont,
                _subtitleFontOptions,
                (value) {
                  if (value == null) return;
                  setState(() => selectedSubtitleFont = value);
                },
                labels: _subtitleFontLabels,
              ),
            ),
            _ghostButton('刷新', refreshSubtitlePreview),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('字幕颜色'),
                const SizedBox(width: 7),
                _colorSquare(subtitleColor),
              ],
            ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('描边颜色'),
                const SizedBox(width: 7),
                _colorSquare(subtitleOutlineColor),
              ],
            ),
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
        const SizedBox(height: 8),
        _readonlyBox(_pipSummaryText),
      ],
    );
  }

  String get _pipSummaryText {
    if (!pipEnabled) return '画中画未启用';
    final name = pipAssetName.isEmpty ? '未选择素材' : pipAssetName;
    if (pipTimingMode == 'time') {
      final start = pipStartController.text.trim().isEmpty
          ? '0'
          : pipStartController.text.trim();
      final end = pipEndController.text.trim();
      return end.isEmpty
          ? '画中画：$name，从 ${start}s 开始'
          : '画中画：$name，${start}s - ${end}s';
    }
    if (pipTimingMode == 'sentence') {
      final trigger = pipTriggerController.text.trim();
      return trigger.isEmpty ? '画中画：$name，按句子显示' : '画中画：$name，触发句：$trigger';
    }
    return '画中画：$name，全程显示';
  }

  Widget _subtitlePresetButton(
    String label,
    Color color,
    Color outlineColor,
    void Function(VoidCallback update) updateDialog,
  ) {
    return OutlinedButton(
      onPressed: () => updateDialog(() {
        subtitleColor = color;
        subtitleOutlineColor = outlineColor;
      }),
      style: OutlinedButton.styleFrom(
        foregroundColor: Colors.white,
        side: BorderSide(color: purpleLine.withValues(alpha: 0.8)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      child: Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
    );
  }

  double _pipHeightForWidth(double width) {
    final height = width * _pipCanvasAspectRatio / _pipMediaAspectRatio;
    return height.clamp(0.04, 1.0).toDouble();
  }

  Rect _pipNormalizedRect() {
    if (pipPosition == 'fullscreen') {
      return const Rect.fromLTWH(0, 0, 1, 1);
    }

    final width = pipScale.clamp(0.1, 0.95).toDouble();
    final height = _pipHeightForWidth(width);
    final maxX = math.max(0.0, 1.0 - width);
    final maxY = math.max(0.0, 1.0 - height);

    final rawX = switch (pipPosition) {
      'top_left' => _pipMarginX,
      'bottom_left' => _pipMarginX,
      'bottom_right' => maxX - _pipMarginX,
      'center' => maxX / 2,
      'custom' => pipX,
      _ => maxX - _pipMarginX,
    };
    final rawY = switch (pipPosition) {
      'bottom_left' => maxY - _pipMarginY,
      'bottom_right' => maxY - _pipMarginY,
      'center' => maxY / 2,
      'custom' => pipY,
      _ => _pipMarginY,
    };

    return Rect.fromLTWH(
      rawX.clamp(0.0, maxX).toDouble(),
      rawY.clamp(0.0, maxY).toDouble(),
      width,
      height,
    );
  }

  void _setPipPosition(String value) {
    if (value == 'custom' && pipPosition != 'custom') {
      final rect = _pipNormalizedRect();
      pipX = rect.left;
      pipY = rect.top;
    }
    pipPosition = value;
    _clampPipCustomPosition();
  }

  void _clampPipCustomPosition() {
    final rect = _pipNormalizedRect();
    final maxX = math.max(0.0, 1.0 - rect.width);
    final maxY = math.max(0.0, 1.0 - rect.height);
    pipX = pipX.clamp(0.0, maxX).toDouble();
    pipY = pipY.clamp(0.0, maxY).toDouble();
  }

  void _updatePreviewState(
    VoidCallback update,
    void Function(VoidCallback update)? updateDialog,
  ) {
    if (updateDialog != null) {
      updateDialog(update);
    } else {
      setState(update);
    }
  }

  void _dragCustomPip(
    DragUpdateDetails details,
    Size canvasSize,
    void Function(VoidCallback update)? updateDialog,
  ) {
    if (pipPosition != 'custom' ||
        canvasSize.width <= 0 ||
        canvasSize.height <= 0) {
      return;
    }
    _updatePreviewState(() {
      pipX += details.delta.dx / canvasSize.width;
      pipY += details.delta.dy / canvasSize.height;
      _clampPipCustomPosition();
    }, updateDialog);
  }

  void _resizeCustomPip(
    DragUpdateDetails details,
    Size canvasSize,
    void Function(VoidCallback update)? updateDialog,
  ) {
    if (pipPosition != 'custom' ||
        canvasSize.width <= 0 ||
        canvasSize.height <= 0) {
      return;
    }
    final widthDelta = details.delta.dx / canvasSize.width;
    final heightDelta = details.delta.dy /
        canvasSize.height /
        (_pipCanvasAspectRatio / _pipMediaAspectRatio);
    final delta =
        widthDelta.abs() > heightDelta.abs() ? widthDelta : heightDelta;
    _updatePreviewState(() {
      pipScale = (pipScale + delta).clamp(0.1, 0.95).toDouble();
      _clampPipCustomPosition();
    }, updateDialog);
  }

  Rect _pipCanvasRect(Size canvasSize) {
    final rect = _pipNormalizedRect();
    return Rect.fromLTWH(
      rect.left * canvasSize.width,
      rect.top * canvasSize.height,
      rect.width * canvasSize.width,
      rect.height * canvasSize.height,
    );
  }

  Widget _subtitlePreviewBox({
    void Function(VoidCallback update)? updateDialog,
  }) {
    final previewText = subtitlePreviewLines.isEmpty
        ? (_renderScript.isEmpty ? '字幕预览' : _renderScript)
        : subtitlePreviewLines.take(3).join('\n');
    return SizedBox(
      height: 320,
      child: Center(
        child: AspectRatio(
          aspectRatio: _pipCanvasAspectRatio,
          child: Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color(0xFF27345F), Color(0xFF11131B)],
              ),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: purpleLine.withValues(alpha: 0.45)),
            ),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final canvasSize =
                    Size(constraints.maxWidth, constraints.maxHeight);
                return Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Center(
                      child: Icon(
                        Icons.person,
                        size: 78,
                        color: Colors.white.withValues(alpha: 0.45),
                      ),
                    ),
                    if (pipEnabled)
                      _pipPreviewLayer(canvasSize, updateDialog: updateDialog),
                    Positioned(
                      left: 10,
                      right: 10,
                      bottom: 14,
                      child: Opacity(
                        opacity: subtitlesEnabled ? 1 : 0.35,
                        child: Text(
                          previewText,
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: subtitleColor,
                            fontSize: subtitleSize.clamp(12, 56).toDouble(),
                            fontFamily: selectedSubtitleFont,
                            fontWeight: FontWeight.w900,
                            height: 1.08,
                            shadows: [
                              Shadow(
                                offset: const Offset(1.8, 1.8),
                                color: subtitleOutlineColor,
                              ),
                              Shadow(
                                offset: const Offset(-1.8, 1.8),
                                color: subtitleOutlineColor,
                              ),
                              Shadow(
                                offset: const Offset(1.8, -1.8),
                                color: subtitleOutlineColor,
                              ),
                              Shadow(
                                offset: const Offset(-1.8, -1.8),
                                color: subtitleOutlineColor,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget _pipPreviewLayer(
    Size canvasSize, {
    void Function(VoidCallback update)? updateDialog,
  }) {
    final rect = _pipCanvasRect(canvasSize);
    final editable = pipPosition == 'custom';
    return Positioned(
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      child: GestureDetector(
        onPanUpdate: editable
            ? (details) => _dragCustomPip(details, canvasSize, updateDialog)
            : null,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Positioned.fill(
              child: Container(
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  color: const Color(0xFF202334),
                  borderRadius: BorderRadius.circular(
                      pipPosition == 'fullscreen' ? 0 : 6),
                  border: Border.all(
                    color: cyan.withValues(alpha: 0.8),
                    width: 2,
                  ),
                ),
                child: pipAssetId.isEmpty
                    ? const Center(
                        child:
                            Icon(Icons.image_outlined, color: Colors.white70),
                      )
                    : _pipPreviewMedia(),
              ),
            ),
            if (editable)
              Positioned(
                right: 4,
                bottom: 4,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: (details) =>
                      _resizeCustomPip(details, canvasSize, updateDialog),
                  child: Container(
                    width: 24,
                    height: 24,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: cyan,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: Colors.white, width: 1.5),
                    ),
                    child: const Icon(
                      Icons.open_in_full,
                      color: Colors.white,
                      size: 13,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _pipPreviewMedia() {
    final previewUrl = '$apiBase/api/pip/$pipAssetId/preview';
    final lowerName = pipAssetName.toLowerCase();
    final isImage = lowerName.endsWith('.png') ||
        lowerName.endsWith('.jpg') ||
        lowerName.endsWith('.jpeg') ||
        lowerName.endsWith('.webp');
    if (!isImage) {
      return const Center(
        child: Icon(Icons.movie_outlined, color: Colors.white70),
      );
    }
    return Image.network(
      previewUrl,
      fit: BoxFit.cover,
      errorBuilder: (_, __, ___) =>
          const Center(child: Icon(Icons.broken_image, color: Colors.white70)),
    );
  }

  Widget _subTabs() {
    final light = _studioLightControls;
    const items = [
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
                            ? light
                                ? studioPrimary
                                : const Color(0xFFD4A4FF)
                            : light
                                ? studioBorder
                                : const Color(0xFF414866),
                        width: selectedMediaSubTab == item.$1 ? 2 : 1,
                      ),
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        item.$2,
                        size: 17,
                        color: selectedMediaSubTab == item.$1
                            ? light
                                ? studioPrimary
                                : const Color(0xFFBFA8FF)
                            : light
                                ? studioMuted
                                : const Color(0xFFBFA8FF),
                      ),
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

  Widget _digitalHumanPreviewImage(String url) {
    return Image.network(
      url,
      fit: BoxFit.cover,
      errorBuilder: (_, __, ___) => _previewPlaceholder(),
    );
  }

  // ignore: unused_element
  Widget _previewBgmButton() {
    final enabled = selectedBgm != 'none';
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: Material(
        color: const Color(0xE61A1D2C),
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: enabled ? playBgm : null,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: purpleLine.withValues(alpha: 0.75)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  _isPlayingBgm ? Icons.stop_rounded : Icons.music_note_rounded,
                  size: 18,
                  color: Colors.white,
                ),
                const SizedBox(width: 6),
                Text(
                  _isPlayingBgm ? '停止BGM' : '播放BGM',
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
              ],
            ),
          ),
        ),
      ),
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
