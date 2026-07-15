import 'dart:math' as math;

/// Converts a linear FFmpeg gain (0.0-1.0) to media_kit/mpv's volume scale.
///
/// mpv cubes `volume / 100` before applying it as an audio gain. Taking the
/// cube root here keeps local preview playback aligned with FFmpeg's linear
/// `volume` filter used by the final render.
double linearGainToMediaKitVolume(double linearGain) {
  final gain = linearGain.clamp(0.0, 1.0).toDouble();
  if (gain == 0) return 0;
  return math.pow(gain, 1 / 3).toDouble() * 100;
}
