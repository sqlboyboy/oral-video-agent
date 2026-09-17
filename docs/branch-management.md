# 分支管理

## 保留的产品分支

| 分支 | 职责 |
|---|---|
| `codex/pc` | GitHub 默认分支，维护 Flutter Windows、配套本地 FastAPI、发布自动化和云端任务能力 |
| `codex/android-apk-no-activation` | 维护 Flutter Android、移动端登录、素材与成品管理、签名 APK 和配套云端能力 |

项目维护以上两个长期产品分支。请根据目标平台选择对应分支。

## 开发与同步

- PC 改动在 `codex/pc` 完成，安卓改动在 `codex/android-apk-no-activation` 完成。
- 两个分支包含各自配套后端，不把其中一个分支整体合并到另一个分支。
- 共享后端修复按具体提交同步，并分别验证接口兼容性。
- 发布前检查本地未提交改动；配置密钥、签名文件、生成素材和安装包不提交到源码仓库。
- 后续部署应明确选择分支，避免继续从已删除的 master 或历史分支拉取代码。

## 验证

客户端在对应分支的 `apps/client` 下执行：

```powershell
flutter analyze lib test
flutter test
```

两个后端分别在 `services/api` 和 `services/cloud` 下执行：

```powershell
uv run pytest tests/ -q
```

本地 API 的部分实验诊断测试需要额外的 PyTorch 环境。完整回归需使用已配置这些依赖的环境；这不意味着安卓手机需要安装 Python 或 PyTorch。

PC 构建入口为 `scripts/package_windows_client_release.ps1`，安卓正式构建入口为安卓分支的 `scripts/build_android_release.ps1`。正式安卓包需要本地签名配置。

代码检查和自动化测试覆盖可重复验证的逻辑。真实 GPU 生成、平台扫码登录与公开发布仍需要在相应运行环境中验证。
