part of 'main.dart';

Future<Map<String, dynamic>>? _mobileVideoTemplateCatalogFuture;

const _mobileFallbackCoverTemplates = <Map<String, dynamic>>[
  {
    'id': 'bold-yellow-white',
    'name': '黄白重磅',
    'description': '黄色重点 · 黑描边',
    'preview_copy': ['爆款标题', '这样写'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#FFD400'},
  },
  {
    'id': 'red-white-emphasis',
    'name': '红白强调',
    'description': '红色重点 · 居中',
    'preview_copy': ['别再这样做', '正确方法'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#FF3B30'},
  },
  {
    'id': 'black-white-clean',
    'name': '黑白极简',
    'description': '纯白粗体 · 紧凑',
    'preview_copy': ['真正的高手', '都很简单'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#FFFFFF'},
  },
  {
    'id': 'blue-white-clear',
    'name': '蓝白清晰',
    'description': '蓝色方法词 · 居中',
    'preview_copy': ['3个方法', '立刻学会'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#35B8FF'},
  },
  {
    'id': 'green-keyword',
    'name': '荧光绿重点',
    'description': '绿色关键词 · 左对齐',
    'preview_copy': ['抓住重点', '效率翻倍'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#58E36D'},
  },
  {
    'id': 'orange-black-impact',
    'name': '橙黑冲击',
    'description': '橙色主标题 · 白重点',
    'preview_copy': ['生意增长', '关键一步'],
    'style': {'fill': '#FF7A22', 'keyword_fill': '#FFFFFF'},
  },
  {
    'id': 'purple-yellow-outline',
    'name': '紫黄双描边',
    'description': '紫描边 · 黄色重点',
    'preview_copy': ['流量密码', '马上告诉你'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#FFE65A'},
  },
  {
    'id': 'offset-shadow',
    'name': '黑白错位',
    'description': '白字 · 硬阴影',
    'preview_copy': ['你以为', '其实不是'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#FFFFFF'},
  },
  {
    'id': 'gold-kaiti',
    'name': '金色楷体',
    'description': '楷体 · 金色层次',
    'preview_copy': ['东方智慧', '尽在其中'],
    'style': {'fill': '#E7C36A', 'keyword_fill': '#FFF3C4'},
  },
  {
    'id': 'vertical-kaiti',
    'name': '竖排楷体',
    'description': '双列竖排 · 白金',
    'preview_copy': ['答案', '藏在细节'],
    'style': {'fill': '#FFFFFF', 'keyword_fill': '#D9B45B'},
  },
];

extension _MobileWorkbench on _WorkbenchPageState {
  Future<Map<String, dynamic>> _mobileVideoTemplateCatalog() {
    return _mobileVideoTemplateCatalogFuture ??=
        _loadMobileVideoTemplateCatalog();
  }

  Future<Map<String, dynamic>> _loadMobileVideoTemplateCatalog() async {
    try {
      final response = await http
          .get(
            Uri.parse('$_cloudApiBase/api/client/video-templates'),
            headers: _cloudHeaders(),
          )
          .timeout(const Duration(seconds: 5));
      _check(response);
      final catalog = jsonDecode(utf8.decode(response.bodyBytes));
      if (catalog is Map<String, dynamic> &&
          catalog['cover_templates'] is List &&
          catalog['subtitle_templates'] is List) {
        return catalog;
      }
    } catch (_) {
      // The bundled templates keep the editor usable while an older cloud
      // service is being upgraded or the phone is temporarily offline.
    }
    return _mobileFallbackVideoTemplateCatalog();
  }

  Map<String, dynamic> _mobileFallbackVideoTemplateCatalog() {
    final subtitleTemplates = _WorkbenchPageState._subtitleTemplates
        .map(
          (template) => <String, dynamic>{
            'id': template.id,
            'name': template.name,
            'industry': template.industry,
            'preview_copy': [template.first, template.second],
            'style': {
              'font_size': template.fontSize,
              'color': _colorHex(template.color),
              'keyword_color': _colorHex(template.keywordColor),
              'outline_color': _colorHex(template.outline),
              'outline_width': template.outlineWidth,
              'font_family': template.font,
              'position': template.position,
              'margin_v': template.marginV,
              'max_chars_per_line': template.maxChars,
            },
          },
        )
        .toList(growable: false);
    return {
      'version': '内置备用',
      'cover_templates': _mobileFallbackCoverTemplates,
      'subtitle_templates': subtitleTemplates,
    };
  }

  Color _mobileTemplateColor(dynamic value, Color fallback) {
    final hex = value?.toString().trim().replaceFirst('#', '') ?? '';
    final parsed = int.tryParse(hex, radix: 16);
    if (parsed == null || (hex.length != 6 && hex.length != 8)) {
      return fallback;
    }
    return Color(hex.length == 6 ? 0xFF000000 | parsed : parsed);
  }

  List<Map<String, dynamic>> _mobileTemplateItems(
    Map<String, dynamic> catalog,
    String key,
  ) {
    return (catalog[key] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList(growable: false);
  }

  void _applyMobileSubtitleTemplate(Map<String, dynamic> template) {
    final style =
        Map<String, dynamic>.from(template['style'] as Map? ?? const {});
    _updateMobile(() {
      selectedSubtitleTemplate =
          template['id']?.toString() ?? selectedSubtitleTemplate;
      subtitlesEnabled = true;
      subtitleSize = (style['font_size'] as num?)?.toDouble() ?? subtitleSize;
      subtitleColor = _mobileTemplateColor(style['color'], subtitleColor);
      subtitleKeywordColor = _mobileTemplateColor(
        style['keyword_color'],
        subtitleKeywordColor,
      );
      subtitleOutlineColor = _mobileTemplateColor(
        style['outline_color'],
        subtitleOutlineColor,
      );
      subtitleOutlineWidth =
          (style['outline_width'] as num?)?.round() ?? subtitleOutlineWidth;
      selectedSubtitleFont =
          style['font_family']?.toString() ?? selectedSubtitleFont;
      subtitlePosition = style['position']?.toString() ?? subtitlePosition;
      subtitleMarginV = (style['margin_v'] as num?)?.round() ?? subtitleMarginV;
      subtitleMaxCharsPerLine =
          (style['max_chars_per_line'] as num?)?.round() ??
              subtitleMaxCharsPerLine;
      finalOutputVideoPath = '';
      finalVideoKey = '';
    });
  }

  void _selectMobileCoverTemplate(Map<String, dynamic> template) {
    _updateMobile(() {
      selectedCoverTemplate =
          template['id']?.toString() ?? selectedCoverTemplate;
      coverPath = '';
      finalOutputVideoPath = '';
      finalVideoKey = '';
    });
  }

  Future<String> _mobileDeviceFingerprint() async {
    final dir = await getApplicationSupportDirectory();
    await dir.create(recursive: true);
    final file = File(
      '${dir.path}${Platform.pathSeparator}mobile_installation_id.txt',
    );
    if (await file.exists()) {
      final existing = (await file.readAsString()).trim();
      if (existing.length >= 16) return existing;
    }
    final random = math.Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    final value = 'android-${base64UrlEncode(bytes).replaceAll('=', '')}';
    await file.writeAsString(value, flush: true);
    return value;
  }

  Widget _mobileAuthScaffold() {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 44, 24, 28),
          child: Column(
            children: [
              Container(
                width: 78,
                height: 78,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [
                      _WorkbenchPageState.cyan,
                      _WorkbenchPageState.pink
                    ],
                  ),
                  borderRadius: BorderRadius.circular(24),
                  boxShadow: [
                    BoxShadow(
                      color:
                          _WorkbenchPageState.purpleLine.withValues(alpha: 0.4),
                      blurRadius: 30,
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.play_arrow_rounded,
                  color: Colors.white,
                  size: 48,
                ),
              ),
              const SizedBox(height: 26),
              const Text(
                '杰速口播',
                style: TextStyle(fontSize: 32, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 10),
              const Text(
                '手机端无需激活码\n注册账号后即可使用云端创作',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white60,
                  fontSize: 15,
                  height: 1.6,
                ),
              ),
              const SizedBox(height: 34),
              _mobileFeatureRow(
                Icons.auto_awesome_rounded,
                'AI 文案仿写',
                '输入文案，一键生成适合口播的脚本',
              ),
              const SizedBox(height: 12),
              _mobileFeatureRow(
                Icons.graphic_eq_rounded,
                '声音克隆',
                '选择手机中的参考声音，云端生成口播音频',
              ),
              const SizedBox(height: 12),
              _mobileFeatureRow(
                Icons.smart_display_rounded,
                '数字人成片',
                '上传形象视频，任务完成后直接在手机预览',
              ),
              const SizedBox(height: 34),
              SizedBox(
                width: double.infinity,
                height: 52,
                child: FilledButton.icon(
                  onPressed:
                      loading ? null : () => _showCloudAuthDialog('register'),
                  icon: const Icon(Icons.person_add_alt_1_rounded),
                  label: const Text(
                    '注册账号',
                    style: TextStyle(fontWeight: FontWeight.w900),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: OutlinedButton.icon(
                  onPressed:
                      loading ? null : () => _showCloudAuthDialog('login'),
                  icon: const Icon(Icons.login_rounded),
                  label: const Text('已有账号，直接登录'),
                ),
              ),
              if (message.isNotEmpty) ...[
                const SizedBox(height: 18),
                _mobileMessageBanner(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _mobileFeatureRow(IconData icon, String title, String subtitle) {
    return Container(
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: const Color(0xFF191B29),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: _WorkbenchPageState.purpleLine.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: const Color(0xFFCAB6FF)),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(fontWeight: FontWeight.w900)),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: const TextStyle(color: Colors.white54, fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _mobileWorkbenchScaffold() {
    final pages = [
      _mobileStudioPage(),
      _mobileVideoPage(),
      _mobileAccountPage(),
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.auto_awesome_rounded, color: Color(0xFFB99AFF)),
            SizedBox(width: 8),
            Text(
              '杰速口播',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900),
            ),
          ],
        ),
        actions: [
          if (loading)
            const Padding(
              padding: EdgeInsets.only(right: 10),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Chip(
              avatar: const Icon(Icons.schedule_rounded, size: 17),
              label: Text(_cloudUsageText),
              side: BorderSide(
                color: _WorkbenchPageState.purpleLine.withValues(alpha: 0.55),
              ),
              backgroundColor: const Color(0xFF24283A),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
              child:
                  IndexedStack(index: mobileNavigationIndex, children: pages)),
          if (message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: _mobileMessageBanner(),
            ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: mobileNavigationIndex,
        onDestinationSelected: (index) {
          _updateMobile(() => mobileNavigationIndex = index);
          if (index == 1) {
            _refreshMobileVideoPage(silent: true);
          } else if (index == 2) {
            loadCloudMe(silent: true);
            loadCloudLedger(silent: true);
          }
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.auto_awesome_outlined),
            selectedIcon: Icon(Icons.auto_awesome_rounded),
            label: '创作',
          ),
          NavigationDestination(
            icon: Icon(Icons.smart_display_outlined),
            selectedIcon: Icon(Icons.smart_display_rounded),
            label: '视频',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline_rounded),
            selectedIcon: Icon(Icons.person_rounded),
            label: '账户',
          ),
        ],
      ),
    );
  }

  Widget _mobileMessageBanner() {
    final color =
        messageIsError ? const Color(0xFFFF7892) : const Color(0xFF65DDB0);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.38)),
      ),
      child: Row(
        children: [
          Icon(
            messageIsError ? Icons.error_outline : Icons.info_outline,
            size: 18,
            color: color,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: color, fontSize: 12),
            ),
          ),
          IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: () => _updateMobile(() => message = ''),
            icon: const Icon(Icons.close_rounded, size: 17),
          ),
        ],
      ),
    );
  }

  Widget _mobileScriptCreationModeSelector() {
    return SizedBox(
      width: double.infinity,
      child: SegmentedButton<String>(
        segments: const [
          ButtonSegment<String>(
            value: 'rewrite',
            icon: Icon(Icons.video_library_outlined, size: 18),
            label: Text('视频仿写'),
          ),
          ButtonSegment<String>(
            value: 'creator',
            icon: Icon(Icons.person_search_rounded, size: 18),
            label: Text('网红风格创作'),
          ),
        ],
        selected: {scriptCreationMode},
        showSelectedIcon: false,
        onSelectionChanged: loading
            ? null
            : (value) => _updateMobile(
                  () => scriptCreationMode = value.first,
                ),
      ),
    );
  }

  Widget _mobileStudioPage() {
    final jobStatus = cloudJob?['status']?.toString() ?? '';
    final jobProgress =
        (cloudJob?['progress_percent'] as num?)?.toDouble() ?? 0;
    final douyinStatus = cloudDouyinTranscription?['status']?.toString() ?? '';
    final douyinProgress =
        (cloudDouyinTranscription?['progress_percent'] as num?)?.toDouble() ??
            0;
    final douyinProgressMessage =
        cloudDouyinTranscription?['progress_message']?.toString() ?? '';
    return RefreshIndicator(
      onRefresh: () async {
        await loadCloudMe(silent: true);
        await loadMobileCloudJobs(silent: true);
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 28),
        children: [
          _mobileCard(
            number: '1',
            title: '准备文案',
            subtitle: scriptCreationMode == 'creator'
                ? '学习网红主页公开内容，结合关键词原创 8 篇文案'
                : '粘贴抖音链接，由服务器下载视频并提取口播原文',
            icon: Icons.edit_note_rounded,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _mobileScriptCreationModeSelector(),
                const SizedBox(height: 12),
                if (scriptCreationMode == 'rewrite') ...[
                  TextField(
                    controller: urlController,
                    minLines: 2,
                    maxLines: 4,
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    enableSuggestions: false,
                    decoration: _mobileInputDecoration(
                      '粘贴抖音分享链接或完整分享口令',
                    ).copyWith(
                      prefixIcon: const Icon(Icons.link_rounded),
                      alignLabelWithHint: true,
                    ),
                  ),
                  const SizedBox(height: 7),
                  const Text(
                    '解析、视频下载、音频提取和语音识别均在服务器完成。',
                    style: TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed:
                          loading ? null : createCloudDouyinTranscriptTask,
                      icon: const Icon(Icons.auto_fix_high_rounded),
                      label: const Text('解析链接并提取文案'),
                    ),
                  ),
                  if (douyinStatus.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    _mobileJobStatus(douyinStatus, douyinProgress),
                    if (douyinProgressMessage.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        douyinProgressMessage,
                        style: const TextStyle(
                          color: Colors.white60,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ],
                  const SizedBox(height: 12),
                  _mobileTextArea(
                    originalScriptController,
                    '输入或粘贴原始口播文案',
                    minLines: 5,
                  ),
                ] else ...[
                  TextField(
                    controller: creatorHomepageController,
                    minLines: 3,
                    maxLines: 5,
                    autocorrect: false,
                    enableSuggestions: false,
                    decoration: _mobileInputDecoration(
                      '粘贴抖音主页链接，或从“4-”开始到末尾的完整分享内容',
                    ).copyWith(
                      prefixIcon: const Icon(Icons.person_search_rounded),
                      alignLabelWithHint: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: creatorKeywordController,
                    decoration: _mobileInputDecoration(
                      '创作关键词，例如：装修',
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '首次读取主页简介和近期 12 个公开作品描述；换一批会直接复用已学习的风格。',
                    style: TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: loading ? null : openCreatorScriptLab,
                      icon: const Icon(Icons.auto_awesome_rounded),
                      label: const Text('分析风格并生成 8 篇'),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '2',
            title: scriptCreationMode == 'creator' ? '确认创作文案' : 'AI 仿写',
            subtitle: scriptCreationMode == 'creator'
                ? '从 8 篇候选中选择后，可在这里继续手动调整'
                : '按产品、受众和风格生成新的口播脚本',
            icon: Icons.auto_awesome_rounded,
            child: Column(
              children: [
                if (scriptCreationMode == 'rewrite') ...[
                  DropdownButtonFormField<String>(
                    initialValue: selectedStyle,
                    decoration: _mobileInputDecoration('改写风格'),
                    items: const [
                      '同款口播',
                      '精简有力',
                      '情绪感染',
                      '专业可信',
                      '种草转化',
                    ]
                        .map((style) => DropdownMenuItem(
                              value: style,
                              child: Text(style),
                            ))
                        .toList(),
                    onChanged: loading
                        ? null
                        : (value) => _updateMobile(
                              () => selectedStyle = value ?? selectedStyle,
                            ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: productController,
                    decoration: _mobileInputDecoration('产品或服务（可选）'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: audienceController,
                    decoration: _mobileInputDecoration('目标人群（可选）'),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: loading ? null : rewrite,
                      icon: const Icon(Icons.bolt_rounded),
                      label: const Text('一键生成改写文案'),
                    ),
                  ),
                  const SizedBox(height: 12),
                ] else if (creatorSelectedLabel.isNotEmpty) ...[
                  Row(
                    children: [
                      const Icon(
                        Icons.check_circle_rounded,
                        color: Color(0xFF65DDB0),
                        size: 18,
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: Text(
                          creatorSelectedLabel,
                          style: const TextStyle(
                            color: Color(0xFF65DDB0),
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                ],
                _mobileTextArea(
                  rewrittenScriptController,
                  scriptCreationMode == 'creator'
                      ? '请先在上一步生成并选择文案；选择后也可以继续手动编辑'
                      : '改写后的文案；也可以继续手动编辑',
                  minLines: 7,
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '3',
            title: '克隆声音',
            subtitle: '支持 WAV/MP3/M4A/AAC/FLAC，最长 3 分钟；较长音频会自动提取克隆片段',
            icon: Icons.graphic_eq_rounded,
            child: Column(
              children: [
                _mobileFileBar(
                  label: mobileVoiceReferenceName.isEmpty
                      ? '尚未选择声音参考'
                      : mobileVoiceReferenceName,
                  buttonText: '选择声音',
                  onPressed: uploadVoice,
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    const Text('成片音量', style: TextStyle(color: Colors.white70)),
                    Expanded(
                      child: Slider(
                        value: voicePreviewVolume,
                        onChanged: loading ? null : _updateVoicePreviewVolume,
                      ),
                    ),
                    Text('${(voicePreviewVolume * 100).round()}%'),
                  ],
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: _cloudVoiceJobActive
                            ? stopCloudVoiceJob
                            : (loading ? null : cloneVoice),
                        icon: Icon(_cloudVoiceJobActive
                            ? Icons.stop_circle_outlined
                            : Icons.record_voice_over_rounded),
                        label: Text(_cloudVoiceJobActive ? '停止克隆' : '克隆声音'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      onPressed: cloudVoiceAudioPath.isEmpty ? null : playVoice,
                      icon: Icon(
                        _isPlayingVoice
                            ? Icons.stop_rounded
                            : Icons.play_arrow_rounded,
                      ),
                      label: Text(_isPlayingVoice ? '停止' : '试听'),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '4',
            title: '选择数字人形象',
            subtitle: '选择正面、清晰、画面稳定的形象视频',
            icon: Icons.smart_display_rounded,
            child: _mobileFileBar(
              label: mobileDigitalHumanName.isEmpty
                  ? '尚未选择形象视频'
                  : mobileDigitalHumanName,
              buttonText: '选择形象',
              onPressed: uploadDigitalHuman,
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '5',
            title: '成片包装',
            subtitle: '简单设置字幕、BGM、画中画和封面',
            icon: Icons.auto_fix_high_rounded,
            child: _mobilePackagingControls(),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '6',
            title: '生成数字人成片',
            subtitle: '确认时长后提交云端任务',
            icon: Icons.movie_creation_outlined,
            child: Column(
              children: [
                TextField(
                  controller: cloudDurationController,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  decoration: _mobileInputDecoration('预计时长（秒）'),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: FilledButton.icon(
                    onPressed: renderingVideo
                        ? stopCloudRender
                        : (loading ? null : renderCloud),
                    icon: Icon(renderingVideo
                        ? Icons.stop_circle_outlined
                        : Icons.movie_creation_outlined),
                    label: Text(renderingVideo ? '停止生成' : '提交云端成片任务'),
                  ),
                ),
                if (jobStatus.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  _mobileJobStatus(jobStatus, jobProgress),
                ],
                if (cloudOutputLocalPath.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: previewOutputVideo,
                          icon: const Icon(Icons.play_circle_outline_rounded),
                          label: const Text('预览成品'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: FilledButton.tonalIcon(
                          onPressed: savingVideoToPhone
                              ? null
                              : _saveMobileOutputVideo,
                          icon: savingVideoToPhone
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.download_rounded),
                          label: Text(
                            savingVideoToPhone ? '保存中' : '保存到相册',
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _mobileSubtitleTemplatePicker() {
    return FutureBuilder<Map<String, dynamic>>(
      future: _mobileVideoTemplateCatalog(),
      builder: (context, snapshot) {
        final catalog = snapshot.data;
        if (catalog == null) {
          return const SizedBox(
            height: 56,
            child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
          );
        }
        final templates = _mobileTemplateItems(catalog, 'subtitle_templates');
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '选择字幕模板',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                _mobileCloudTemplateBadge(catalog['version']?.toString()),
              ],
            ),
            const SizedBox(height: 9),
            SizedBox(
              height: 142,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: templates.length,
                separatorBuilder: (_, __) => const SizedBox(width: 9),
                itemBuilder: (_, index) =>
                    _mobileSubtitleTemplateCard(templates[index]),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _mobileSubtitleTemplateCard(Map<String, dynamic> template) {
    final id = template['id']?.toString() ?? '';
    final selected = selectedSubtitleTemplate == id;
    final style =
        Map<String, dynamic>.from(template['style'] as Map? ?? const {});
    final preview = (template['preview_copy'] as List? ?? const [])
        .map((item) => item.toString())
        .toList(growable: false);
    final color = _mobileTemplateColor(style['color'], Colors.white);
    final keywordColor = _mobileTemplateColor(style['keyword_color'], color);
    final outline = _mobileTemplateColor(style['outline_color'], Colors.black);
    final shadows = [
      Shadow(color: outline, offset: const Offset(-1, 0)),
      Shadow(color: outline, offset: const Offset(1, 0)),
      Shadow(color: outline, offset: const Offset(0, -1)),
      Shadow(color: outline, offset: const Offset(0, 1)),
    ];
    return SizedBox(
      width: 194,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(13),
          onTap: loading ? null : () => _applyMobileSubtitleTemplate(template),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: selected
                  ? _WorkbenchPageState.purpleLine.withValues(alpha: 0.18)
                  : const Color(0xFF11131E),
              borderRadius: BorderRadius.circular(13),
              border: Border.all(
                color: selected ? const Color(0xFFB99AFF) : Colors.white12,
                width: selected ? 1.6 : 1,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        template['name']?.toString() ?? id,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    if (selected)
                      const Icon(
                        Icons.check_circle_rounded,
                        color: Color(0xFFB99AFF),
                        size: 17,
                      ),
                  ],
                ),
                const Spacer(),
                Center(
                  child: Column(
                    children: [
                      Text(
                        preview.isEmpty ? '字幕预览' : preview.first,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: color,
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          shadows: shadows,
                        ),
                      ),
                      if (preview.length > 1)
                        Text(
                          preview[1],
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: keywordColor,
                            fontSize: 16,
                            fontWeight: FontWeight.w900,
                            shadows: shadows,
                          ),
                        ),
                    ],
                  ),
                ),
                const Spacer(),
                Text(
                  template['industry']?.toString() ?? '通用',
                  style: const TextStyle(color: Colors.white38, fontSize: 10),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _mobileCoverTemplatePicker() {
    return FutureBuilder<Map<String, dynamic>>(
      future: _mobileVideoTemplateCatalog(),
      builder: (context, snapshot) {
        final catalog = snapshot.data;
        if (catalog == null) {
          return const SizedBox(
            height: 56,
            child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
          );
        }
        final templates = _mobileTemplateItems(catalog, 'cover_templates');
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '选择封面模板',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                _mobileCloudTemplateBadge(catalog['version']?.toString()),
              ],
            ),
            const SizedBox(height: 9),
            SizedBox(
              height: 132,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: templates.length,
                separatorBuilder: (_, __) => const SizedBox(width: 9),
                itemBuilder: (_, index) =>
                    _mobileCoverTemplateCard(templates[index]),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _mobileCoverTemplateCard(Map<String, dynamic> template) {
    final id = template['id']?.toString() ?? '';
    final selected = selectedCoverTemplate == id;
    final style =
        Map<String, dynamic>.from(template['style'] as Map? ?? const {});
    final preview = (template['preview_copy'] as List? ?? const [])
        .map((item) => item.toString())
        .toList(growable: false);
    final fill = _mobileTemplateColor(style['fill'], Colors.white);
    final keyword = _mobileTemplateColor(style['keyword_fill'], fill);
    const shadows = [
      Shadow(color: Colors.black, offset: Offset(-1.2, 0)),
      Shadow(color: Colors.black, offset: Offset(1.2, 0)),
      Shadow(color: Colors.black, offset: Offset(0, 1.2)),
    ];
    return SizedBox(
      width: 194,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(13),
          onTap: loading ? null : () => _selectMobileCoverTemplate(template),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: selected
                  ? _WorkbenchPageState.purpleLine.withValues(alpha: 0.18)
                  : const Color(0xFF11131E),
              borderRadius: BorderRadius.circular(13),
              border: Border.all(
                color: selected ? const Color(0xFFB99AFF) : Colors.white12,
                width: selected ? 1.6 : 1,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        template['name']?.toString() ?? id,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    if (selected)
                      const Icon(
                        Icons.check_circle_rounded,
                        color: Color(0xFFB99AFF),
                        size: 17,
                      ),
                  ],
                ),
                const Spacer(),
                Text(
                  preview.isEmpty ? '视频标题' : preview.first,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: fill,
                    fontSize: 19,
                    fontWeight: FontWeight.w900,
                    shadows: shadows,
                  ),
                ),
                if (preview.length > 1)
                  Text(
                    preview[1],
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: keyword,
                      fontSize: 17,
                      fontWeight: FontWeight.w900,
                      shadows: shadows,
                    ),
                  ),
                const Spacer(),
                Text(
                  template['description']?.toString() ?? '透明纯文字',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white38, fontSize: 10),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _mobileCloudTemplateBadge(String? version) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: const Color(0xFFB99AFF).withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        '云端 ${version ?? ''}'.trim(),
        style: const TextStyle(color: Color(0xFFCAB6FF), fontSize: 9),
      ),
    );
  }

  Widget _mobilePackagingControls() {
    final hasBgm = selectedBgm != 'none' && mobileBgmPath.isNotEmpty;
    final currentCover = _currentCoverPath;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SwitchListTile.adaptive(
          contentPadding: EdgeInsets.zero,
          dense: true,
          value: subtitlesEnabled,
          onChanged: loading
              ? null
              : (value) => _updateMobile(() => subtitlesEnabled = value),
          title:
              const Text('显示字幕', style: TextStyle(fontWeight: FontWeight.w800)),
          subtitle: const Text('默认黄字黑边，位于画面下方'),
        ),
        if (subtitlesEnabled) ...[
          _mobileSubtitleTemplatePicker(),
        ],
        const Divider(height: 28),
        const Text('背景音乐', style: TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        _mobileFileBar(
          label: hasBgm ? mobileBgmName : '不使用背景音乐',
          buttonText: hasBgm ? '更换 BGM' : '选择 BGM',
          onPressed: uploadBgm,
        ),
        if (hasBgm) ...[
          Row(
            children: [
              const Text('BGM 音量', style: TextStyle(color: Colors.white70)),
              Expanded(
                child: Slider(
                  value: bgmVolume,
                  onChanged: loading ? null : _updateBgmVolume,
                ),
              ),
              Text('${(bgmVolume * 100).round()}%'),
            ],
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: loading
                  ? null
                  : () => _updateMobile(() {
                        mobileBgmPath = '';
                        mobileBgmName = '';
                        selectedBgm = 'none';
                      }),
              icon: const Icon(Icons.delete_outline_rounded),
              label: const Text('移除 BGM'),
            ),
          ),
        ],
        const Divider(height: 28),
        SwitchListTile.adaptive(
          contentPadding: EdgeInsets.zero,
          dense: true,
          value: pipEnabled,
          onChanged: loading
              ? null
              : (value) => _updateMobile(() => pipEnabled = value),
          title:
              const Text('画中画', style: TextStyle(fontWeight: FontWeight.w800)),
          subtitle: const Text('将图片或视频叠加到数字人画面'),
        ),
        if (pipEnabled) ...[
          _mobileFileBar(
            label: pipAssetName.isEmpty ? '尚未选择画中画素材' : pipAssetName,
            buttonText: '选择素材',
            onPressed: uploadPipAsset,
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            key: ValueKey('mobile-pip-$pipPosition'),
            initialValue: pipPosition,
            decoration: _mobileInputDecoration('画中画位置'),
            items: const {
              'top_left': '左上',
              'top_right': '右上',
              'bottom_left': '左下',
              'bottom_right': '右下',
              'fullscreen': '全屏',
            }
                .entries
                .map((entry) => DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ))
                .toList(),
            onChanged: loading
                ? null
                : (value) => _updateMobile(
                      () => pipPosition = value ?? pipPosition,
                    ),
          ),
          if (pipPosition != 'fullscreen')
            Row(
              children: [
                const Text('画中画大小', style: TextStyle(color: Colors.white70)),
                Expanded(
                  child: Slider(
                    min: 0.18,
                    max: 0.55,
                    value: pipScale.clamp(0.18, 0.55).toDouble(),
                    onChanged: loading
                        ? null
                        : (value) => _updateMobile(() => pipScale = value),
                  ),
                ),
                Text('${(pipScale * 100).round()}%'),
              ],
            ),
        ],
        const Divider(height: 28),
        const Text('视频封面', style: TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 5),
        const Text(
          '纯文字模板写入视频首帧，也可选择 9:16 图片',
          style: TextStyle(color: Colors.white54, fontSize: 12),
        ),
        const SizedBox(height: 9),
        _mobileCoverTemplatePicker(),
        const SizedBox(height: 9),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: loading ? null : generateCover,
              icon: const Icon(Icons.auto_awesome_rounded),
              label: const Text('生成封面'),
            ),
            OutlinedButton.icon(
              onPressed: loading ? null : uploadCover,
              icon: const Icon(Icons.add_photo_alternate_outlined),
              label: const Text('选择图片'),
            ),
          ],
        ),
        if (currentCover != null) ...[
          const SizedBox(height: 10),
          Center(
            child: SizedBox(
              height: 180,
              child: AspectRatio(
                aspectRatio: 9 / 16,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.file(
                    File(currentCover),
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const ColoredBox(
                      color: Colors.white10,
                      child: Icon(Icons.broken_image_outlined),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _mobileCard({
    required String number,
    required String title,
    required String subtitle,
    required IconData icon,
    required Widget child,
  }) {
    return Container(
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: const Color(0xFF181A27),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF303348)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [
                      _WorkbenchPageState.cyan,
                      _WorkbenchPageState.pink
                    ],
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    Icon(icon,
                        color: Colors.white.withValues(alpha: 0.32), size: 30),
                    Text(
                      number,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w900),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      style:
                          const TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 15),
          child,
        ],
      ),
    );
  }

  Widget _mobileFileBar({
    required String label,
    required String buttonText,
    required VoidCallback onPressed,
  }) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      decoration: BoxDecoration(
        color: const Color(0xFF12141F),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: Colors.white12),
      ),
      child: Row(
        children: [
          const Icon(Icons.attach_file_rounded,
              color: Colors.white54, size: 19),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ),
          const SizedBox(width: 6),
          OutlinedButton(
            onPressed: loading ? null : onPressed,
            child: Text(buttonText),
          ),
        ],
      ),
    );
  }

  Widget _mobileTextArea(
    TextEditingController controller,
    String hint, {
    int minLines = 4,
  }) {
    return TextField(
      controller: controller,
      minLines: minLines,
      maxLines: minLines + 4,
      keyboardType: TextInputType.multiline,
      decoration: _mobileInputDecoration(hint),
    );
  }

  InputDecoration _mobileInputDecoration(String hint) {
    return InputDecoration(
      hintText: hint,
      filled: true,
      fillColor: const Color(0xFF12141F),
      contentPadding: const EdgeInsets.symmetric(horizontal: 13, vertical: 12),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(11)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(11),
        borderSide: const BorderSide(color: Color(0xFF34374B)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(11),
        borderSide: const BorderSide(color: _WorkbenchPageState.cyan),
      ),
    );
  }

  Widget _mobileJobStatus(String status, double progress) {
    final color = _mobileCloudStatusColor(status);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.cloud_queue_rounded, color: color, size: 18),
              const SizedBox(width: 7),
              Text(
                _cloudStatusText(status),
                style: TextStyle(color: color, fontWeight: FontWeight.w900),
              ),
              const Spacer(),
              Text('${progress.round()}%', style: TextStyle(color: color)),
            ],
          ),
          if (const {'uploading', 'queued', 'running'}.contains(status)) ...[
            const SizedBox(height: 9),
            LinearProgressIndicator(
              value: progress > 0 ? progress.clamp(0, 100) / 100 : null,
              color: color,
              backgroundColor: Colors.white10,
            ),
          ],
        ],
      ),
    );
  }

  Widget _mobileVideoPage() {
    final outputPath = cloudOutputLocalPath.trim();
    final outputUrl = cloudOutputUrl.trim();
    final sourcePath = mobileDigitalHumanPath.trim();
    final hasLocalOutput =
        outputPath.isNotEmpty && File(outputPath).existsSync();
    final hasOutput = hasLocalOutput || outputUrl.isNotEmpty;
    final hasSource = sourcePath.isNotEmpty;
    final status = cloudJob?['status']?.toString() ?? '';
    final progress = (cloudJob?['progress_percent'] as num?)?.toDouble() ?? 0;
    final renderActive =
        const {'uploading', 'queued', 'running'}.contains(status);
    final title = hasOutput ? '成品视频' : '数字人原视频';
    final fileName = hasOutput
        ? _cloudOutputLabel
        : (mobileDigitalHumanName.isEmpty
            ? _fileNameFromPath(sourcePath)
            : mobileDigitalHumanName);

    return RefreshIndicator(
      onRefresh: () => _refreshMobileVideoPage(silent: true),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 28),
        children: [
          Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '我的数字人视频',
                      style:
                          TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
                    ),
                    SizedBox(height: 3),
                    Text(
                      '生成前显示原视频，生成完成后自动替换为成品视频',
                      style: TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
              IconButton.filledTonal(
                onPressed: loading
                    ? null
                    : () => _refreshMobileVideoPage(silent: false),
                icon: const Icon(Icons.refresh_rounded),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (!hasOutput && !hasSource) ...[
            _mobileEmptyState(
              '还没有数字人视频',
              '请先在创作页面选择并上传数字人形象视频',
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: () => _updateMobile(() => mobileNavigationIndex = 0),
              icon: const Icon(Icons.upload_file_rounded),
              label: const Text('去上传数字人视频'),
            ),
          ] else ...[
            _mobileVideoCard(
              title: title,
              fileName: fileName,
              isOutput: hasOutput,
              renderActive: renderActive,
              progress: progress,
            ),
          ],
        ],
      ),
    );
  }

  Widget _mobileVideoCard({
    required String title,
    required String fileName,
    required bool isOutput,
    required bool renderActive,
    required double progress,
  }) {
    final cover = isOutput ? _currentCoverPath : null;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF181A27),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFF34384D)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 300),
              child: AspectRatio(
                aspectRatio: 9 / 16,
                child: Material(
                  color: Colors.transparent,
                  child: InkWell(
                    onTap: _playMobileVideo,
                    borderRadius: BorderRadius.circular(18),
                    child: Ink(
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(18),
                        gradient: LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: isOutput
                              ? const [Color(0xFF49317B), Color(0xFF171926)]
                              : const [Color(0xFF283C66), Color(0xFF171926)],
                        ),
                        border: Border.all(color: Colors.white12),
                      ),
                      child: Stack(
                        children: [
                          if (cover != null) ...[
                            Positioned.fill(
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(18),
                                child: Image.file(
                                  File(cover),
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) =>
                                      const SizedBox.shrink(),
                                ),
                              ),
                            ),
                            Positioned.fill(
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(18),
                                  color: Colors.black26,
                                ),
                              ),
                            ),
                          ],
                          Positioned(
                            left: 14,
                            top: 14,
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.black38,
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                title,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ),
                          ),
                          Center(
                            child: Container(
                              width: 78,
                              height: 78,
                              decoration: const BoxDecoration(
                                color: Colors.white24,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.play_arrow_rounded,
                                color: Colors.white,
                                size: 52,
                              ),
                            ),
                          ),
                          if (renderActive && !isOutput)
                            const Positioned(
                              left: 14,
                              right: 14,
                              bottom: 14,
                              child: Text(
                                '成品生成中，当前仍显示原视频',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Colors.white70,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          Text(
            fileName,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
          ),
          const SizedBox(height: 5),
          Text(
            isOutput ? '已生成成品视频' : '用户上传的数字人原视频',
            style: const TextStyle(color: Colors.white54, fontSize: 12),
          ),
          if (renderActive && !isOutput) ...[
            const SizedBox(height: 14),
            LinearProgressIndicator(
              value: progress > 0 ? progress.clamp(0, 100) / 100 : null,
              color: _WorkbenchPageState.cyan,
              backgroundColor: Colors.white10,
            ),
          ],
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _playMobileVideo,
              icon: const Icon(Icons.play_circle_outline_rounded),
              label: Text(isOutput ? '播放成品视频' : '播放数字人原视频'),
            ),
          ),
          if (isOutput) ...[
            const SizedBox(height: 9),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: savingVideoToPhone ? null : _saveMobileOutputVideo,
                icon: savingVideoToPhone
                    ? const SizedBox(
                        width: 17,
                        height: 17,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.download_rounded),
                label: Text(
                  savingVideoToPhone ? '正在保存视频' : '保存到相册',
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _refreshMobileVideoPage({required bool silent}) async {
    try {
      await loadMobileCloudJobs(silent: true);
      final job = cloudJob;
      final jobId = job?['job_id']?.toString() ?? '';
      final jobType = job?['job_type']?.toString() ?? '';
      final status = job?['status']?.toString() ?? '';
      if (jobId.isNotEmpty && jobType != 'preprocess') {
        if (const {'uploading', 'queued', 'running'}.contains(status)) {
          await _pollCloudJob(jobId);
        } else if (status == 'completed') {
          final outputPath = await _ensureCloudOutputFile(jobId);
          if (outputPath == null) throw Exception('云端成品下载失败');
        }
      }
      if (!silent && mounted) showInfo('视频状态已刷新');
    } catch (error) {
      if (!silent) showError(_friendlyError(error));
    }
  }

  Future<void> _playMobileVideo() async {
    if (cloudOutputLocalPath.isNotEmpty || cloudOutputUrl.isNotEmpty) {
      await previewOutputVideo();
      return;
    }
    final sourcePath = mobileDigitalHumanPath.trim();
    if (sourcePath.isEmpty || !await File(sourcePath).exists()) {
      showError('数字人原视频不存在，请重新选择');
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _VideoPlayerDialog(url: sourcePath),
    );
  }

  Future<void> _saveMobileOutputVideo() async {
    if (!_isAndroidClient || savingVideoToPhone) return;
    final jobId = _cloudJobId;
    String? path;
    try {
      if (jobId != null &&
          (cloudJob?['status']?.toString() ?? '') == 'completed') {
        path = await _ensureCloudOutputFile(jobId);
      } else if (await _isUsableLocalMp4(cloudOutputLocalPath)) {
        path = cloudOutputLocalPath.trim();
      }
    } catch (_) {
      showError('成品文件已不在云端，请重新生成；新版本会保留云端副本供失败时重试');
      return;
    }
    if (path == null || !await _isUsableLocalMp4(path)) {
      showError('成品视频不存在，请刷新状态或重新生成');
      return;
    }
    final now = DateTime.now();
    String twoDigits(int value) => value.toString().padLeft(2, '0');
    final fileName = 'jiesu-video-${now.year}'
        '${twoDigits(now.month)}${twoDigits(now.day)}-'
        '${twoDigits(now.hour)}${twoDigits(now.minute)}${twoDigits(now.second)}.mp4';
    _updateMobile(() {
      savingVideoToPhone = true;
      message = '正在保存到“杰速口播”相册';
      messageIsError = false;
    });
    try {
      final savedUri = await _androidPlatformChannel.invokeMethod<String>(
        'saveVideo',
        {'path': path, 'file_name': fileName},
      );
      if (!mounted) return;
      _updateMobile(() {
        message = savedUri == null ? '视频保存失败，请重试' : '视频已保存到“杰速口播”相册';
        messageIsError = false;
      });
    } on PlatformException catch (error) {
      if (!mounted) return;
      showError('视频保存失败：${error.message ?? error.code}');
    } finally {
      if (mounted) _updateMobile(() => savingVideoToPhone = false);
    }
  }

  Widget _mobileAccountPage() {
    final access = cloudUsageAccess ??
        (_cloudUser?['usage_access'] as Map?)?.cast<String, dynamic>() ??
        const <String, dynamic>{};
    final email = _cloudUser?['email']?.toString() ?? '未登录';
    return RefreshIndicator(
      onRefresh: () async {
        await loadCloudMe(silent: true);
        await loadCloudLedger(silent: true);
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 28),
        children: [
          _mobileCard(
            number: '✓',
            title: '我的账户',
            subtitle: '手机端注册后即可使用，无需输入激活码',
            icon: Icons.person_rounded,
            child: Column(
              children: [
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: Color(0xFF7046D9),
                    child: Icon(Icons.person, color: Colors.white),
                  ),
                  title: Text(email,
                      style: const TextStyle(fontWeight: FontWeight.w900)),
                  subtitle: const Text('云端账号'),
                  trailing: IconButton(
                    tooltip: '刷新账户',
                    onPressed: () async {
                      await loadCloudMe(silent: true);
                      await loadCloudLedger(silent: true);
                    },
                    icon: const Icon(Icons.refresh_rounded),
                  ),
                ),
                const Divider(),
                Row(
                  children: [
                    Expanded(
                      child: _mobileMetric(
                        '剩余使用期限',
                        _cloudUsageText,
                        const Color(0xFF65DDB0),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _mobileMetric(
                        '到期时间',
                        _cloudUsageExpiryText,
                        const Color(0xFFFFC857),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: logoutCloudAccount,
                    icon: const Icon(Icons.logout_rounded),
                    label: const Text('退出登录'),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            decoration: BoxDecoration(
              color: const Color(0xFF181A27),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0xFF303348)),
            ),
            child: ListTile(
              leading: const Icon(
                Icons.system_update_rounded,
                color: Color(0xFFB99AFF),
              ),
              title: const Text(
                '检查应用更新',
                style: TextStyle(fontWeight: FontWeight.w900),
              ),
              subtitle: Text(
                mobileAppVersion.isEmpty ? '获取当前版本中' : '当前版本 $mobileAppVersion',
              ),
              trailing: mobileUpdateChecking
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.chevron_right_rounded),
              onTap: mobileUpdateChecking
                  ? null
                  : () => _checkForMobileUpdate(silent: false),
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: const Color(0xFF181A27),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0xFF303348)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '使用规则',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 10),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    access['has_access'] == true
                        ? Icons.check_circle_rounded
                        : Icons.schedule_rounded,
                    color: access['has_access'] == true
                        ? const Color(0xFF65DDB0)
                        : const Color(0xFFFFC857),
                  ),
                  title: Text(
                    access['has_access'] == true ? '有效期内不限次数' : '剩余期限为 0天0小时0分',
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                  subtitle: Text(
                    access['has_access'] == true
                        ? '生成文案、声音和视频均免费'
                        : '请联系管理员开通或增加使用期限',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _mobileMetric(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.09),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(color: Colors.white54, fontSize: 12)),
          const SizedBox(height: 4),
          SizedBox(
            width: double.infinity,
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                value,
                style: TextStyle(
                  color: color,
                  fontSize: 21,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _mobileEmptyState(String title, String subtitle) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 34),
      decoration: BoxDecoration(
        color: const Color(0xFF141620),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        children: [
          const Icon(Icons.inbox_outlined, size: 38, color: Colors.white30),
          const SizedBox(height: 9),
          Text(title, style: const TextStyle(fontWeight: FontWeight.w900)),
          const SizedBox(height: 4),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white38, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Color _mobileCloudStatusColor(String status) {
    return switch (status) {
      'completed' => const Color(0xFF65DDB0),
      'failed' || 'timed_out' => const Color(0xFFFF7892),
      'canceled' => Colors.white54,
      'running' => _WorkbenchPageState.cyan,
      _ => const Color(0xFFFFC857),
    };
  }
}
