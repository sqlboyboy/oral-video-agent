import 'package:flutter_test/flutter_test.dart';
import 'package:oral_video_agent_client/cloud_upload_matcher.dart';

void main() {
  test('按素材类型匹配云端上传槽位，不依赖返回顺序', () {
    final order = matchCloudUploadAssetOrder(
      assets: const [
        {
          'kind': 'voice_audio',
          'file_name': 'voice.wav',
        },
        {
          'kind': 'source_video',
          'file_name': 'avatar.mp4',
        },
      ],
      uploads: const [
        CloudUploadDescriptor(
          kind: 'source_video',
          fileName: 'avatar.mp4',
        ),
        CloudUploadDescriptor(
          kind: 'voice_audio',
          fileName: 'voice.wav',
        ),
      ],
    );

    expect(order, [1, 0]);
  });

  test('同类型素材优先按文件名精确匹配', () {
    final order = matchCloudUploadAssetOrder(
      assets: const [
        {
          'kind': 'pip_asset',
          'file_name': 'second.mp4',
        },
        {
          'kind': 'pip_asset',
          'file_name': 'first.mp4',
        },
      ],
      uploads: const [
        CloudUploadDescriptor(
          kind: 'pip_asset',
          fileName: 'first.mp4',
        ),
        CloudUploadDescriptor(
          kind: 'pip_asset',
          fileName: 'second.mp4',
        ),
      ],
    );

    expect(order, [1, 0]);
  });
}
