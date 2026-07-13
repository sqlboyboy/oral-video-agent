part of 'main.dart';

extension _MobileWorkbench on _WorkbenchPageState {
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
    final wallet = cloudWallet ?? const <String, dynamic>{};
    final points = wallet['available_points'] ?? 0;
    final pages = [
      _mobileStudioPage(),
      _mobileTasksPage(),
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
              avatar: const Icon(Icons.toll_rounded, size: 17),
              label: Text('$points 点'),
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
            loadMobileCloudJobs(silent: true);
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
            icon: Icon(Icons.format_list_bulleted_rounded),
            label: '任务',
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

  Widget _mobileStudioPage() {
    final jobStatus = cloudJob?['status']?.toString() ?? '';
    final jobProgress =
        (cloudJob?['progress_percent'] as num?)?.toDouble() ?? 0;
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
            subtitle: '可直接输入，也可从手机视频提取口播原文',
            icon: Icons.edit_note_rounded,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _mobileFileBar(
                  label: cloudSourceVideoName.isEmpty
                      ? '尚未选择源视频'
                      : cloudSourceVideoName,
                  buttonText: '选择视频',
                  onPressed: uploadSourceVideo,
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: loading || cloudSourceVideoPath.isEmpty
                        ? null
                        : createCloudTranscriptTask,
                    icon: const Icon(Icons.auto_fix_high_rounded),
                    label: const Text('从视频提取文案'),
                  ),
                ),
                const SizedBox(height: 12),
                _mobileTextArea(
                  originalScriptController,
                  '输入或粘贴原始口播文案',
                  minLines: 5,
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '2',
            title: 'AI 仿写',
            subtitle: '按产品、受众和风格生成新的口播脚本',
            icon: Icons.auto_awesome_rounded,
            child: Column(
              children: [
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
                _mobileTextArea(
                  rewrittenScriptController,
                  '改写后的文案；也可以继续手动编辑',
                  minLines: 7,
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          _mobileCard(
            number: '3',
            title: '克隆声音',
            subtitle: '建议选择 15–60 秒清晰人声，最长不超过 5 分钟',
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
            title: '生成数字人成片',
            subtitle: '选择正面、清晰、画面稳定的形象视频',
            icon: Icons.smart_display_rounded,
            child: Column(
              children: [
                _mobileFileBar(
                  label: mobileDigitalHumanName.isEmpty
                      ? '尚未选择形象视频'
                      : mobileDigitalHumanName,
                  buttonText: '选择形象',
                  onPressed: uploadDigitalHuman,
                ),
                const SizedBox(height: 10),
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
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: previewOutputVideo,
                      icon: const Icon(Icons.play_circle_outline_rounded),
                      label: const Text('预览成品视频'),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
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

  Widget _mobileTasksPage() {
    return RefreshIndicator(
      onRefresh: () => loadMobileCloudJobs(silent: true),
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
                      '云端任务',
                      style:
                          TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
                    ),
                    SizedBox(height: 3),
                    Text(
                      '下拉或点击按钮刷新任务进度',
                      style: TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
              IconButton.filledTonal(
                onPressed: loading ? null : loadMobileCloudJobs,
                icon: const Icon(Icons.refresh_rounded),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (mobileCloudJobs.isEmpty)
            _mobileEmptyState('还没有云端任务', '完成声音克隆或提交成片后会显示在这里')
          else
            for (final job in mobileCloudJobs) ...[
              _mobileCloudJobCard(job),
              const SizedBox(height: 10),
            ],
        ],
      ),
    );
  }

  Widget _mobileCloudJobCard(Map<String, dynamic> job) {
    final status = job['status']?.toString() ?? '';
    final jobId = job['job_id']?.toString() ?? '';
    final jobType = job['job_type']?.toString() ?? 'render';
    final progress = (job['progress_percent'] as num?)?.toDouble() ?? 0;
    final active = const {'uploading', 'queued', 'running'}.contains(status);
    final color = _mobileCloudStatusColor(status);
    final payload = (job['payload'] as Map?)?.cast<String, dynamic>();
    final operation = payload?['operation']?.toString() ?? '';
    final title = jobType == 'preprocess'
        ? (operation == 'voice'
            ? '声音克隆任务'
            : operation == 'extract'
                ? '文案提取任务'
                : '云端预处理任务')
        : '数字人成片任务';
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF181A27),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: color.withValues(alpha: 0.32)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.13),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(
                  jobType == 'preprocess'
                      ? Icons.graphic_eq_rounded
                      : Icons.movie_outlined,
                  color: color,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                    const SizedBox(height: 2),
                    Text(
                      jobId,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style:
                          const TextStyle(color: Colors.white38, fontSize: 10),
                    ),
                  ],
                ),
              ),
              Text(
                _cloudStatusText(status),
                style: TextStyle(color: color, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          if (active) ...[
            const SizedBox(height: 12),
            LinearProgressIndicator(
              value: progress > 0 ? progress.clamp(0, 100) / 100 : null,
              color: color,
              backgroundColor: Colors.white10,
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: Text(
                  job['progress_message']?.toString().isNotEmpty == true
                      ? job['progress_message'].toString()
                      : '创建于 ${job['created_at'] ?? ''}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white54, fontSize: 11),
                ),
              ),
              if (active)
                TextButton.icon(
                  onPressed: () => _mobileCancelCloudJob(job),
                  icon: const Icon(Icons.stop_circle_outlined, size: 18),
                  label: const Text('停止'),
                )
              else if (status == 'completed' && jobType == 'render')
                TextButton.icon(
                  onPressed: () => _mobileOpenCloudJob(job),
                  icon: const Icon(Icons.play_circle_outline_rounded, size: 18),
                  label: const Text('预览'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _mobileCancelCloudJob(Map<String, dynamic> job) async {
    _updateMobile(() => cloudJob = job);
    await stopCloudRender();
    await loadMobileCloudJobs(silent: true);
  }

  Future<void> _mobileOpenCloudJob(Map<String, dynamic> job) async {
    _updateMobile(() {
      cloudJob = job;
      mobileNavigationIndex = 0;
      message = '正在准备云端成品';
      messageIsError = false;
    });
    final jobId = job['job_id']?.toString() ?? '';
    if (jobId.isEmpty) return;
    try {
      await _loadCloudDownload(jobId);
      if (!mounted) return;
      await previewOutputVideo();
    } catch (error) {
      showError(_friendlyError(error));
    }
  }

  Widget _mobileAccountPage() {
    final wallet = cloudWallet ?? const <String, dynamic>{};
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
                        '可用点数',
                        '${wallet['available_points'] ?? 0}',
                        const Color(0xFF65DDB0),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _mobileMetric(
                        '冻结点数',
                        '${wallet['frozen_points'] ?? 0}',
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
                  '最近点数明细',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 10),
                if (cloudLedger.isEmpty)
                  _mobileEmptyState('暂无点数明细', '云端任务的点数变化会显示在这里')
                else
                  for (final item in cloudLedger.take(12))
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.bolt_rounded,
                          color: Color(0xFFB99AFF)),
                      title: Text(_ledgerTitle(item)),
                      trailing: Text(
                        '${item['points'] ?? ''}',
                        style: const TextStyle(
                          color: Color(0xFFFFC857),
                          fontWeight: FontWeight.w900,
                        ),
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
          Text(
            '$value 点',
            style: TextStyle(
                color: color, fontSize: 21, fontWeight: FontWeight.w900),
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
