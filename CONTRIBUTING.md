# 参与贡献

## 选择产品分支

- Windows 改动基于 `codex/pc`。
- Android 改动基于 `codex/android-apk-no-activation`。
- 涉及共享后端时，说明影响的客户端和需要同步的改动。

## 提交前检查

在 `apps/client` 执行 `flutter analyze lib test` 和 `flutter test`。

在改动涉及的后端目录执行 `uv run pytest tests/ -q`。部分本地 API 实验诊断测试依赖 PyTorch；需要完整回归时，为测试环境额外安装它：

```powershell
cd services/api
uv run --with torch pytest tests/ -q
```

无需启动模型服务即可运行使用占位 Provider 或模拟请求的测试。真实 GPU 推理、平台登录与发布应单独验证，并说明验证范围。

## 凭据检查

仓库使用 Gitleaks 检查提交历史。安装 Gitleaks 后可在根目录运行：

```bash
gitleaks git --redact=100 --log-opts=--all
```

提交前也可用 `gitleaks git --pre-commit --redact=100` 检查暂存内容。`.gitleaks.toml` 仅放行已确认的迁移标识与示例令牌，不要为真实凭据添加忽略规则。

`.env`、签名文件、Cookie、浏览器登录目录、运行数据和内部交接记录不进入 Git。公开问题报告中使用示例域名和测试账号。

## Issue 与 PR

Issue 请提供产品分支、运行环境、复现步骤、预期与实际结果，以及脱敏日志。

PR 请说明解决的问题、行为变化、测试结果和限制。不要附带账号凭据、用户素材或不相关的生成文件。
