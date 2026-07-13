# 云端管理后台

管理后台直接复用 `services/cloud` 的用户、软件授权、点数钱包、点数流水、设备和任务数据。

## 访问与登录

部署后访问：

```text
http://你的云端域名或 IP/admin
```

在 `services/cloud/deploy/.env` 配置管理员账号：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请替换为强密码
ADMIN_COOKIE_SECURE=false
```

当前使用 HTTP 时保持 `ADMIN_COOKIE_SECURE=false`；切换 HTTPS 后应改为 `true`。如果暂未配置
`ADMIN_PASSWORD`，系统会兼容使用现有 `ADMIN_TOKEN` 作为后台登录密码。

## 已有功能

- 账号密码登录、12 小时登录态和退出登录。
- 一键生成软件激活码，默认授权 1 台设备且不赠送点数。
- 一键新增邮箱用户，同时创建现有点数钱包和该用户的专属激活码。
- 按邮箱查询用户，查看付费点数、赠送点数、冻结点数和点数流水。
- 给用户充值付费点数，流水事件沿用 `admin_credit`。
- 查看用户设备、云端任务、授权状态，支持停用账号和重置设备绑定。
- 查看账号、钱包、激活码和任务汇总数据。

专属激活码通过客户端现有 `/api/client/activate` 接口激活时，会绑定到后台预创建的同一个
邮箱用户，不会生成重复账号。
