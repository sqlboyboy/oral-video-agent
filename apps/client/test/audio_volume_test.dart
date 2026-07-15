import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:oral_video_agent_client/audio_volume.dart';

void main() {
  group('linearGainToMediaKitVolume', () {
    test('preserves silence and unity gain', () {
      expect(linearGainToMediaKitVolume(0), 0);
      expect(linearGainToMediaKitVolume(1), closeTo(100, 1e-9));
    });

    test('inverts mpv cubic volume curve', () {
      for (final linearGain in [0.1, 0.35, 0.45, 0.8]) {
        final mediaKitVolume = linearGainToMediaKitVolume(linearGain);
        final effectiveGain = math.pow(mediaKitVolume / 100, 3);
        expect(effectiveGain, closeTo(linearGain, 1e-9));
      }
    });

    test('clamps values to the supported linear gain range', () {
      expect(linearGainToMediaKitVolume(-0.5), 0);
      expect(linearGainToMediaKitVolume(2), closeTo(100, 1e-9));
    });
  });
}
