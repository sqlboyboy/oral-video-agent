part of 'main.dart';

const MethodChannel _androidPlatformChannel = MethodChannel(
  'com.jiesu.oral_video_agent_client/updater',
);

class _MobileRelease {
  const _MobileRelease({
    required this.versionName,
    required this.versionCode,
    required this.updateAvailable,
    required this.forceUpdate,
    required this.downloadUri,
    required this.sha256Hex,
    required this.sizeBytes,
    required this.releaseNotes,
  });

  final String versionName;
  final int versionCode;
  final bool updateAvailable;
  final bool forceUpdate;
  final Uri downloadUri;
  final String sha256Hex;
  final int sizeBytes;
  final List<String> releaseNotes;

  factory _MobileRelease.fromJson(
    Map<String, dynamic> json,
    String cloudApiBase,
  ) {
    final downloadUrl = json['download_url']?.toString().trim() ?? '';
    final sha = json['sha256']?.toString().trim().toLowerCase() ?? '';
    final versionCode = (json['version_code'] as num?)?.toInt() ?? 0;
    final sizeBytes = (json['size_bytes'] as num?)?.toInt() ?? 0;
    final baseUri = Uri.parse('$cloudApiBase/');
    final downloadUri = baseUri.resolve(downloadUrl);
    final rawNotes = json['release_notes'];
    final releaseNotes = rawNotes is List
        ? rawNotes
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList(growable: false)
        : const <String>[];
    if (versionCode <= 0 ||
        downloadUrl.isEmpty ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(sha) ||
        sizeBytes <= 0) {
      throw const FormatException('服务器返回的更新信息不完整');
    }
    return _MobileRelease(
      versionName: json['version_name']?.toString().trim() ?? '',
      versionCode: versionCode,
      updateAvailable: json['update_available'] == true,
      forceUpdate: json['force_update'] == true,
      downloadUri: downloadUri,
      sha256Hex: sha,
      sizeBytes: sizeBytes,
      releaseNotes: releaseNotes,
    );
  }
}

class _MobileDownloadProgress {
  const _MobileDownloadProgress(this.receivedBytes, this.totalBytes);

  final int receivedBytes;
  final int totalBytes;

  double? get fraction =>
      totalBytes <= 0 ? null : (receivedBytes / totalBytes).clamp(0, 1);
}

extension _MobileUpdater on _WorkbenchPageState {
  Future<String?> _readAndroidSecureValue(String key) {
    return _androidPlatformChannel.invokeMethod<String>(
      'readSecureValue',
      {'key': key},
    );
  }

  Future<void> _writeAndroidSecureValue(String key, String value) {
    return _androidPlatformChannel.invokeMethod<void>(
      'writeSecureValue',
      {'key': key, 'value': value},
    );
  }

  Future<void> _deleteAndroidSecureValue(String key) {
    return _androidPlatformChannel.invokeMethod<void>(
      'deleteSecureValue',
      {'key': key},
    );
  }

  Future<void> _loadMobilePackageVersion() async {
    try {
      final info = await PackageInfo.fromPlatform();
      if (!mounted) return;
      _updateMobile(
          () => mobileAppVersion = '${info.version} (${info.buildNumber})');
    } catch (_) {
      // 版本展示失败不影响登录和创作。
    }
  }

  Future<void> _checkForMobileUpdate({required bool silent}) async {
    if (!_isAndroidClient || mobileUpdateChecking) return;
    if (!_isSecureCloudBase(_cloudApiBase)) {
      if (!silent) showError('应用更新仅允许通过 HTTPS 安全连接检查');
      return;
    }
    if (mounted) _updateMobile(() => mobileUpdateChecking = true);
    try {
      final info = await PackageInfo.fromPlatform();
      final currentVersionCode = int.tryParse(info.buildNumber) ?? 0;
      final uri = Uri.parse('$_cloudApiBase/api/mobile/releases/latest')
          .replace(queryParameters: {
        'version_code': currentVersionCode.toString(),
      });
      final response = await http.get(
        uri,
        headers: const {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 12));
      if (response.statusCode == 404) {
        if (!silent) showInfo('服务器暂未发布安卓更新');
        return;
      }
      _check(response);
      final release =
          _MobileRelease.fromJson(_decodeMap(response), _cloudApiBase);
      if (!release.updateAvailable ||
          release.versionCode <= currentVersionCode) {
        if (!silent) showInfo('当前已经是最新版本');
        return;
      }
      if (!mounted) return;
      await _showMobileUpdateDialog(release);
    } catch (error) {
      if (!silent) showError('检查更新失败：${_friendlyError(error)}');
    } finally {
      if (mounted) _updateMobile(() => mobileUpdateChecking = false);
    }
  }

  Future<void> _showMobileUpdateDialog(_MobileRelease release) async {
    final notes = release.releaseNotes.isEmpty
        ? const ['修复已知问题并提升使用体验']
        : release.releaseNotes;
    final accepted = await showDialog<bool>(
      context: context,
      barrierDismissible: !release.forceUpdate,
      builder: (dialogContext) => PopScope(
        canPop: !release.forceUpdate,
        child: AlertDialog(
          title: Text(release.forceUpdate ? '发现重要更新' : '发现新版本'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '杰速口播 ${release.versionName}（${release.versionCode}）',
                style: const TextStyle(fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 12),
              for (final note in notes)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text('• $note'),
                ),
              const SizedBox(height: 8),
              Text(
                '安装包大小：${_formatMobileBytes(release.sizeBytes)}',
                style: const TextStyle(color: Colors.white60),
              ),
            ],
          ),
          actions: [
            if (!release.forceUpdate)
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('稍后更新'),
              ),
            FilledButton.icon(
              onPressed: () => Navigator.pop(dialogContext, true),
              icon: const Icon(Icons.download_rounded),
              label: const Text('安全下载并安装'),
            ),
          ],
        ),
      ),
    );
    if (accepted == true && mounted) {
      await _downloadAndInstallMobileUpdate(release);
    }
  }

  Future<void> _downloadAndInstallMobileUpdate(_MobileRelease release) async {
    if (!_isSecureCloudBase(release.downloadUri.toString())) {
      showError('更新包下载地址不是安全的 HTTPS 地址');
      return;
    }
    final installAllowed = await _ensureMobileInstallPermission();
    if (!installAllowed || !mounted) {
      showError('未获得安装应用权限，暂时无法继续更新');
      return;
    }

    final progress = ValueNotifier<_MobileDownloadProgress>(
      _MobileDownloadProgress(0, release.sizeBytes),
    );
    BuildContext? progressContext;
    unawaited(showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        progressContext = dialogContext;
        return PopScope(
          canPop: false,
          child: AlertDialog(
            title: const Text('正在安全下载更新'),
            content: ValueListenableBuilder<_MobileDownloadProgress>(
              valueListenable: progress,
              builder: (_, value, __) => Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  LinearProgressIndicator(value: value.fraction),
                  const SizedBox(height: 12),
                  Text(
                    '${_formatMobileBytes(value.receivedBytes)} / '
                    '${_formatMobileBytes(value.totalBytes)}',
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    '下载完成后会校验安装包完整性',
                    style: TextStyle(color: Colors.white60, fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    ));

    File? apkFile;
    try {
      apkFile = await _downloadMobileApk(release, progress);
      final digest = await sha256.bind(apkFile.openRead()).first;
      if (digest.toString().toLowerCase() != release.sha256Hex) {
        await apkFile.delete();
        throw const FormatException('安装包完整性校验失败，文件已删除');
      }
    } catch (error) {
      if (progressContext != null && progressContext!.mounted) {
        Navigator.of(progressContext!).pop();
      }
      progress.dispose();
      if (mounted) showError('更新下载失败：${_friendlyError(error)}');
      return;
    }

    if (progressContext != null && progressContext!.mounted) {
      Navigator.of(progressContext!).pop();
    }
    progress.dispose();
    if (!mounted) return;
    try {
      await _androidPlatformChannel.invokeMethod<void>(
        'installApk',
        {'path': apkFile.path},
      );
    } on PlatformException catch (error) {
      showError('打开系统安装界面失败：${error.message ?? error.code}');
    }
  }

  Future<File> _downloadMobileApk(
    _MobileRelease release,
    ValueNotifier<_MobileDownloadProgress> progress,
  ) async {
    const maxApkBytes = 300 * 1024 * 1024;
    if (release.sizeBytes > maxApkBytes) {
      throw const FormatException('更新包超过 300 MB 安全限制');
    }
    final tempDir = await getTemporaryDirectory();
    final updateDir = Directory(
      '${tempDir.path}${Platform.pathSeparator}updates',
    );
    await updateDir.create(recursive: true);
    await for (final entity in updateDir.list()) {
      if (entity is File && entity.path.toLowerCase().endsWith('.apk')) {
        try {
          await entity.delete();
        } catch (_) {
          // 旧缓存删除失败时继续使用新的唯一文件名。
        }
      }
    }
    final apkFile = File(
      '${updateDir.path}${Platform.pathSeparator}'
      'jiesu-update-${release.versionCode}.apk',
    );
    final client = http.Client();
    IOSink? sink;
    try {
      final request = http.Request('GET', release.downloadUri);
      final response =
          await client.send(request).timeout(const Duration(seconds: 20));
      if (response.statusCode != 200) {
        throw HttpException('服务器返回 ${response.statusCode}');
      }
      final contentLength = response.contentLength ?? release.sizeBytes;
      if (contentLength <= 0 || contentLength > maxApkBytes) {
        throw const FormatException('服务器返回的安装包大小异常');
      }
      sink = apkFile.openWrite();
      var received = 0;
      await for (final chunk
          in response.stream.timeout(const Duration(seconds: 30))) {
        received += chunk.length;
        if (received > maxApkBytes || received > release.sizeBytes + 1024) {
          throw const FormatException('下载数据超过服务器声明的大小');
        }
        sink.add(chunk);
        progress.value = _MobileDownloadProgress(received, contentLength);
      }
      await sink.flush();
      await sink.close();
      sink = null;
      if (received != release.sizeBytes) {
        throw const FormatException('安装包下载不完整');
      }
      return apkFile;
    } catch (_) {
      try {
        await sink?.close();
        if (await apkFile.exists()) await apkFile.delete();
      } catch (_) {
        // 清理失败不覆盖原始下载错误。
      }
      rethrow;
    } finally {
      client.close();
    }
  }

  Future<bool> _ensureMobileInstallPermission() async {
    final allowed = await _androidPlatformChannel
            .invokeMethod<bool>('canRequestPackageInstalls') ??
        false;
    if (allowed || !mounted) return allowed;
    final shouldOpen = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('允许安装更新'),
        content: const Text(
          '安卓需要你为“杰速口播”开启一次“允许安装未知应用”权限。'
          '该权限只用于安装本应用经过校验的更新包。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('去授权'),
          ),
        ],
      ),
    );
    if (shouldOpen != true) return false;

    final resumed = Completer<void>();
    var leftApp = false;
    final listener = AppLifecycleListener(
      onPause: () => leftApp = true,
      onResume: () {
        if (leftApp && !resumed.isCompleted) resumed.complete();
      },
    );
    try {
      await _androidPlatformChannel.invokeMethod<void>('openInstallPermission');
      await resumed.future.timeout(const Duration(minutes: 2));
    } catch (_) {
      // 用户可能通过系统返回键或超时离开授权页，下面统一重新检查。
    } finally {
      listener.dispose();
    }
    return await _androidPlatformChannel
            .invokeMethod<bool>('canRequestPackageInstalls') ??
        false;
  }

  String _formatMobileBytes(int bytes) {
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    if (bytes >= 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '$bytes B';
  }
}
