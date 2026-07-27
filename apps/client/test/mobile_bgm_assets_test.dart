import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('四首内置 BGM 均已打包进 Flutter 资源', () async {
    const assets = [
      'assets/bgm/热门bgm2.mp3',
      'assets/bgm/热门bgm1.mp3',
      'assets/bgm/欢快配音1.mp3',
      'assets/bgm/欢快背景音乐2.mp3',
    ];

    for (final asset in assets) {
      final data = await rootBundle.load(asset);
      expect(data.lengthInBytes, greaterThan(100000), reason: asset);
    }
  });
}
