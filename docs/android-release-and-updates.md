# 安卓正式发布与远程更新

## 当前发布基线

- 应用 ID：`com.jiesu.oral_video_agent_client`
- 当前正式版本：`0.2.2+5`
- 首个正式签名版本：`0.2.0+3`
- 云端 API：`https://api.example.com`
- 更新检查：`GET /api/mobile/releases/latest?version_code=<当前版本号>`
- APK 下载：由更新接口返回相对 HTTPS 地址

此前的 `0.1.1+2` 测试包使用调试签名，无法被正式签名版本覆盖安装。第一次切换时必须卸载
测试包并安装当前正式版本 `0.2.2+5`；从 `0.2.0+3` 开始，只要一直保留相同的正式签名密钥，后续版本即可
覆盖更新。

## 安全规则

1. `android-release.jks` 和 `android/key.properties` 永远不得提交 Git。
2. 两个签名文件必须至少保存两份离线加密备份。密钥丢失后无法更新已安装的正式版。
3. 正式构建只接受 HTTPS `CLOUD_API_BASE`。
4. 正式 APK 使用 Dart 混淆和独立调试符号；调试符号只用于还原崩溃堆栈，不能发布。
5. 更新包下载到应用私有缓存，校验 SHA-256 后才交给 Android 系统安装器。
6. Android 8 及以上首次更新时，用户需要为杰速口播授权“允许安装未知应用”。
7. 登录令牌由 Android Keystore 管理的 AES-GCM 密钥加密保存，普通 JSON 只保存邮箱和非敏感配置。

## 构建与发布

首次配置正式签名：

```powershell
.\scripts\configure_android_release_signing.ps1
```

构建正式混淆 APK 和 `latest.json`：

```powershell
.\scripts\build_android_release.ps1
```

发布到腾讯云服务器：

```powershell
.\scripts\publish_android_release.ps1
```

发布脚本会在上传前核对 APK 与清单的 SHA-256，并最后原子替换 `latest.json`，避免客户端
读到尚未上传完成的安装包。

## HTTPS 运维

生产服务器使用 Let's Encrypt 受信任的短期 IP 证书，证书自动续期定时器为：

```text
oral-video-cert-renew.timer
```

服务器安全组必须长期开放 TCP/80 和 TCP/443：80 用于 ACME 证书验证并把业务流量重定向
到 HTTPS，443 用于全部 API、后台和 APK 下载。生产环境必须保持：

```dotenv
ADMIN_COOKIE_SECURE=true
CLOUD_PUBLIC_BASE_URL=https://api.example.com
ANDROID_RELEASE_DIR=/data/releases/android
```
