import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class CreatorScriptCandidate {
  const CreatorScriptCandidate({
    required this.candidateId,
    required this.title,
    required this.angle,
    required this.script,
    required this.reason,
  });

  factory CreatorScriptCandidate.fromJson(Map<String, dynamic> json) {
    return CreatorScriptCandidate(
      candidateId: json['candidate_id']?.toString() ?? '',
      title: json['title']?.toString().trim() ?? '',
      angle: json['angle']?.toString().trim() ?? '',
      script: json['script']?.toString().trim() ?? '',
      reason: json['reason']?.toString().trim() ?? '',
    );
  }

  final String candidateId;
  final String title;
  final String angle;
  final String script;
  final String reason;
}

class CreatorScriptSelection {
  const CreatorScriptSelection({
    required this.batchId,
    required this.creatorName,
    required this.keyword,
    required this.candidate,
  });

  final String batchId;
  final String creatorName;
  final String keyword;
  final CreatorScriptCandidate candidate;
}

class CreatorScriptLabDialog extends StatefulWidget {
  const CreatorScriptLabDialog({
    super.key,
    required this.apiBase,
    required this.shareText,
    required this.keyword,
  });

  final String apiBase;
  final String shareText;
  final String keyword;

  @override
  State<CreatorScriptLabDialog> createState() => _CreatorScriptLabDialogState();
}

class _CreatorScriptLabDialogState extends State<CreatorScriptLabDialog> {
  static const _primary = Color(0xFF5B5CEB);
  static const _primaryDark = Color(0xFF4546D7);
  static const _ink = Color(0xFF171A2B);
  static const _muted = Color(0xFF747B91);
  static const _border = Color(0xFFE5E8F0);
  static const _canvas = Color(0xFFF5F6FA);

  List<CreatorScriptCandidate> _items = const [];
  Map<String, dynamic>? _styleProfile;
  String _batchId = '';
  String _creatorName = '';
  String _selectedCandidateId = '';
  int _generationRound = 0;
  bool _loading = false;
  String _error = '';

  CreatorScriptCandidate? get _selectedCandidate {
    if (_items.isEmpty) return null;
    for (final item in _items) {
      if (item.candidateId == _selectedCandidateId) return item;
    }
    return _items.first;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _generate());
  }

  Future<void> _generate({bool regenerate = false}) async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final nextRound = regenerate ? _generationRound + 1 : 1;
      final requestBody = <String, dynamic>{
        'share_text': regenerate ? '' : widget.shareText,
        'keyword': widget.keyword,
        'count': 8,
        'duration_seconds': 60,
        'generation_round': nextRound,
        if (regenerate && _styleProfile != null) 'style_profile': _styleProfile,
        if (regenerate)
          'exclude_titles': _items.map((item) => item.title).toList(),
      };
      final response = await http
          .post(
            Uri.parse('${widget.apiBase}/api/creator-scripts/generate'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode(requestBody),
          )
          .timeout(const Duration(minutes: 3));
      final decodedText = utf8.decode(response.bodyBytes);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception(_responseError(decodedText, response.statusCode));
      }
      final decoded = jsonDecode(decodedText);
      if (decoded is! Map) {
        throw const FormatException('服务返回的数据格式不正确');
      }
      final body = decoded.cast<String, dynamic>();
      final rawItems = body['items'];
      if (rawItems is! List) {
        throw const FormatException('服务没有返回候选文案');
      }
      final items = rawItems
          .whereType<Map>()
          .map(
            (item) => CreatorScriptCandidate.fromJson(
              item.cast<String, dynamic>(),
            ),
          )
          .where((item) => item.script.isNotEmpty)
          .toList(growable: false);
      if (items.isEmpty) {
        throw const FormatException('服务没有生成有效的候选文案');
      }
      final rawProfile = body['style_profile'];
      if (!mounted) return;
      setState(() {
        _items = items;
        _batchId = body['batch_id']?.toString() ?? '';
        _creatorName = body['creator_name']?.toString().trim() ?? '';
        _generationRound =
            int.tryParse(body['generation_round']?.toString() ?? '') ??
                nextRound;
        _styleProfile = rawProfile is Map
            ? rawProfile.cast<String, dynamic>()
            : _styleProfile;
        _selectedCandidateId = items.first.candidateId;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _responseError(String responseText, int statusCode) {
    try {
      final decoded = jsonDecode(responseText);
      if (decoded is Map && decoded['detail'] != null) {
        final detail = decoded['detail'];
        if (detail is List) {
          return detail
              .map((item) => item is Map ? item['msg'] ?? item : item)
              .join('；');
        }
        return detail.toString();
      }
    } catch (_) {
      // Fall through to a compact HTTP error below.
    }
    return '生成失败（HTTP $statusCode）';
  }

  String _friendlyError(Object error) {
    final text = error.toString();
    if (text.startsWith('Exception: ')) return text.substring(11);
    if (text.startsWith('FormatException: ')) return text.substring(17);
    return text;
  }

  void _useSelected() {
    final selected = _selectedCandidate;
    if (selected == null) return;
    Navigator.of(context).pop(
      CreatorScriptSelection(
        batchId: _batchId.isEmpty
            ? DateTime.now().millisecondsSinceEpoch.toString()
            : _batchId,
        creatorName: _creatorName,
        keyword: widget.keyword,
        candidate: selected,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final screenSize = MediaQuery.sizeOf(context);
    return Dialog(
      insetPadding: const EdgeInsets.all(22),
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      child: SizedBox(
        width: mathMin(1180, screenSize.width - 44),
        height: mathMin(820, screenSize.height - 44),
        child: Column(
          children: [
            _header(),
            if (_loading) const LinearProgressIndicator(minHeight: 3),
            Expanded(child: _body()),
            _footer(),
          ],
        ),
      ),
    );
  }

  double mathMin(num first, num second) =>
      (first < second ? first : second).toDouble();

  Widget _header() {
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 18, 14, 18),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: _border)),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: const Color(0xFFEEEFFF),
              borderRadius: BorderRadius.circular(13),
            ),
            child: const Icon(Icons.psychology_alt_rounded, color: _primary),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '网红风格创作 · 深度学习',
                  style: TextStyle(
                    color: _ink,
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  _creatorName.isEmpty
                      ? '分析主页公开内容，结合“${widget.keyword}”生成 8 篇全新口播文案'
                      : '已学习 $_creatorName 的表达风格 · 关键词：${widget.keyword}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: _muted, fontSize: 13),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: '关闭',
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.close_rounded),
          ),
        ],
      ),
    );
  }

  Widget _body() {
    if (_items.isEmpty) {
      return ColoredBox(
        color: _canvas,
        child: Center(
          child: SizedBox(
            width: 520,
            child: _error.isNotEmpty ? _emptyError() : _initialLoading(),
          ),
        ),
      );
    }
    return ColoredBox(
      color: _canvas,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            SizedBox(width: 365, child: _candidateList()),
            const SizedBox(width: 16),
            Expanded(child: _candidateDetail()),
          ],
        ),
      ),
    );
  }

  Widget _initialLoading() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 74,
          height: 74,
          decoration: const BoxDecoration(
            color: Color(0xFFEAEBFF),
            shape: BoxShape.circle,
          ),
          child: const Center(
            child: SizedBox(
              width: 30,
              height: 30,
              child: CircularProgressIndicator(strokeWidth: 3),
            ),
          ),
        ),
        const SizedBox(height: 20),
        const Text(
          '正在读取抖音主页并学习创作风格',
          style: TextStyle(
            color: _ink,
            fontSize: 18,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 9),
        const Text(
          '会分析主页简介和近期公开作品，再生成 8 个不同角度的候选文案。首次分析可能需要一些时间。',
          textAlign: TextAlign.center,
          style: TextStyle(color: _muted, height: 1.6),
        ),
      ],
    );
  }

  Widget _emptyError() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.error_outline_rounded,
            color: Color(0xFFD94C59), size: 50),
        const SizedBox(height: 15),
        const Text(
          '这次没有生成成功',
          style: TextStyle(
            color: _ink,
            fontSize: 18,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          _error,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Color(0xFFB03C48), height: 1.5),
        ),
        const SizedBox(height: 18),
        FilledButton.icon(
          onPressed: _loading ? null : () => _generate(),
          icon: const Icon(Icons.refresh_rounded),
          label: const Text('重新分析'),
        ),
      ],
    );
  }

  Widget _candidateList() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _border),
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 15, 16, 12),
            child: Row(
              children: [
                const Text(
                  '候选文案',
                  style: TextStyle(
                    color: _ink,
                    fontSize: 16,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const Spacer(),
                _badge('第 $_generationRound 轮'),
                const SizedBox(width: 6),
                _badge('${_items.length} 篇'),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.all(10),
              itemCount: _items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final item = _items[index];
                return _candidateTile(item, index);
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _candidateTile(CreatorScriptCandidate item, int index) {
    final selected = _selectedCandidate?.candidateId == item.candidateId;
    return Material(
      color: selected ? const Color(0xFFEEEFFF) : Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => setState(() => _selectedCandidateId = item.candidateId),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected ? const Color(0xFFB8BAFF) : _border,
              width: selected ? 1.5 : 1,
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 28,
                height: 28,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: selected ? _primary : const Color(0xFFF0F2F6),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${index + 1}',
                  style: TextStyle(
                    color: selected ? Colors.white : _muted,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title.isEmpty ? '未命名文案' : item.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: _ink,
                        fontSize: 14,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    if (item.angle.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        item.angle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: selected ? _primaryDark : _muted,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                    const SizedBox(height: 5),
                    Text(
                      item.script,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Color(0xFF656C80),
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
              if (selected) ...[
                const SizedBox(width: 6),
                const Icon(Icons.check_circle_rounded,
                    color: _primary, size: 20),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _candidateDetail() {
    final item = _selectedCandidate;
    if (item == null) return const SizedBox.shrink();
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 18, 22, 15),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.title.isEmpty ? '候选文案' : item.title,
                        style: const TextStyle(
                          color: _ink,
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    if (item.angle.isNotEmpty) _badge(item.angle),
                  ],
                ),
                if (item.reason.isNotEmpty) ...[
                  const SizedBox(height: 9),
                  Text(
                    item.reason,
                    style: const TextStyle(color: _muted, height: 1.45),
                  ),
                ],
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 28),
              child: SelectableText(
                item.script,
                style: const TextStyle(
                  color: _ink,
                  fontSize: 16,
                  height: 1.9,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ),
          if (_error.isNotEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
              color: const Color(0xFFFFF0F1),
              child: Text(
                '重新生成失败：$_error（上一批文案已保留）',
                style: const TextStyle(
                  color: Color(0xFFB03C48),
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _badge(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F1FF),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          color: _primaryDark,
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }

  Widget _footer() {
    final canUse = _selectedCandidate != null && !_loading;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: _border)),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline_rounded, color: _muted, size: 18),
          const SizedBox(width: 7),
          const Expanded(
            child: Text(
              '候选文案为风格学习后的全新创作；只有点击“使用选中文案”才会写入当前项目。',
              style: TextStyle(color: _muted, fontSize: 12),
            ),
          ),
          OutlinedButton.icon(
            onPressed: _items.isEmpty || _loading
                ? null
                : () => _generate(regenerate: true),
            icon: const Icon(Icons.refresh_rounded),
            label: Text(_loading ? '正在生成' : '不满意，换一批'),
          ),
          const SizedBox(width: 10),
          FilledButton.icon(
            onPressed: canUse ? _useSelected : null,
            style: FilledButton.styleFrom(
              backgroundColor: _primary,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            ),
            icon: const Icon(Icons.check_rounded),
            label: const Text(
              '使用选中文案',
              style: TextStyle(fontWeight: FontWeight.w900),
            ),
          ),
        ],
      ),
    );
  }
}
