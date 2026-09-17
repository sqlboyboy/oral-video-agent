class CloudUploadDescriptor {
  const CloudUploadDescriptor({
    required this.kind,
    required this.fileName,
  });

  final String kind;
  final String fileName;
}

/// Matches cloud upload slots to local files without relying on response order.
///
/// The cloud database may return assets with identical timestamps in a
/// different order from the upload-session request. Matching by kind and file
/// name prevents source videos and voice audio from being uploaded to each
/// other's slots.
List<int> matchCloudUploadAssetOrder({
  required List<Map<String, dynamic>> assets,
  required List<CloudUploadDescriptor> uploads,
}) {
  if (assets.length != uploads.length) {
    throw StateError('云端返回的素材上传槽位数量不正确');
  }

  final unmatched = List<int>.generate(uploads.length, (index) => index);
  final result = <int>[];

  for (final asset in assets) {
    final kind = asset['kind']?.toString() ?? '';
    final fileName = asset['file_name']?.toString() ?? '';
    var matchAt = unmatched.indexWhere((index) {
      final upload = uploads[index];
      return upload.kind == kind && upload.fileName == fileName;
    });
    matchAt = matchAt >= 0
        ? matchAt
        : unmatched.indexWhere((index) => uploads[index].kind == kind);
    matchAt = matchAt >= 0
        ? matchAt
        : unmatched.indexWhere((index) => uploads[index].fileName == fileName);
    if (matchAt < 0) {
      throw StateError('云端返回了无法匹配的素材上传槽位：$kind / $fileName');
    }
    result.add(unmatched.removeAt(matchAt));
  }

  return result;
}
