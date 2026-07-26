import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oral_video_agent_client/creator_script_lab.dart';

void main() {
  testWidgets('长标题和长创作角度在桌面详情区不会溢出', (tester) async {
    tester.view.physicalSize = const Size(1750, 1246);
    tester.view.devicePixelRatio = 1.5;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final items = List.generate(
      8,
      (index) => {
        'candidate_id': 'candidate-$index',
        'title': '水电改造最容易漏掉的三根线以及施工过程中必须逐项确认的验收细节',
        'angle': '从水电隐蔽工程中常被忽视的细节切入，用具体数字清单强化紧迫感，直接点出业主最容易遗漏的位置',
        'script': '水电改造时师傅不会主动告诉你这三根线\n'
            '第一根线关系到厨房设备使用\n'
            '第二根线影响后期检修\n'
            '第三根线决定入住后的便利程度',
        'reason': '采用数字清单结构，开场制造信息差，逐项列举具体位置和后果。',
      },
    );
    final client = MockClient(
      (request) async => http.Response(
        jsonEncode({
          'batch_id': 'batch-1',
          'creator_name': '老师讲装修',
          'keyword': '装修',
          'generation_round': 1,
          'style_profile': {
            'creator_name': '老师讲装修',
            'summary': '实用装修经验',
          },
          'items': items,
        }),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CreatorScriptLabDialog(
            endpoint: 'http://127.0.0.1:8001/api/creator-scripts/generate',
            shareText: 'https://v.douyin.com/example/',
            keyword: '装修',
            client: client,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('水电改造最容易漏掉'), findsWidgets);
    expect(find.textContaining('从水电隐蔽工程'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
