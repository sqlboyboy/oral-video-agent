# 安卓端的数据架构与软件工作流程

> 依据本地 `Android` 分支代码整理。描述代码实现，不代表已经核验线上部署状态。

## 1. 整体分工

安卓应用采用 Flutter/Dart 编写界面，通过 Kotlin 衔接安全存储、相册保存和 APK 安装等原生功能。手机调用云端业务 API，云端控制中心管理账号、点数和任务，AutoDL Worker 执行需要模型推理的生成工作。

系统的数据分为四层：

| 层级 | 存放位置 | 主要内容 | 职责 |
|---|---|---|---|
| 手机端数据 | 应用内存、应用目录、Android 安全存储、相册 | 当前编辑内容、登录凭据、素材路径、音视频缓存、已保存成品 | 支撑交互、登录恢复和本地播放 |
| 云端业务数据 | PostgreSQL；未配置数据库连接时可使用 SQLite | 用户、设备、钱包、任务、素材索引、任务事件 | 决定任务归属、计费与业务状态 |
| 云端媒体文件 | 腾讯云 COS | 人物视频、参考声音、生成音频、BGM、封面、成品 MP4 | 保存和传输大文件 |
| 计算与临时数据 | AutoDL 工作目录、模型服务 | 下载素材、任务参数、中间音视频、待上传结果 | 执行生成任务 |

Redis 额外承担限流和队列状态辅助记录。任务的持久化记录与领取逻辑位于数据库层。

## 2. 手机端的数据结构

### 2.1 当前页面与编辑状态

Flutter 使用 StatefulWidget、setState 和控制器保存当前文案、已选素材、字幕及封面设置、当前任务、进度、下载状态等。

这些页面状态主要位于内存中，不能把它们都视为已经持久保存的草稿。云端已提交任务可以重新查询；尚未提交的编辑内容是否能恢复，要看对应功能是否写入本地存储。

### 2.2 登录数据

- `cloud_auth.json`：保存云端 API 地址、邮箱、退出状态、存储版本等配置。
- 登录相关令牌：通过 MethodChannel 交给 Kotlin，使用 Android Keystore 管理的密钥进行 AES-GCM 加密，密文存入应用私有 SharedPreferences。
- `mobile_installation_id.txt`：保存随机生成的安装标识，作为该安装实例的设备指纹，不是手机硬件序列号。

安卓当前实现会把旧版本 JSON 中的令牌迁移到安全存储。请求业务 API 时使用 Bearer 令牌；服务端据此识别设备和用户。

### 2.3 手机媒体文件

用户选择的素材以本地路径参与后续操作；云端生成的声音和视频会下载到应用目录，用于试听、预览以及后续步骤。

“下载到应用目录”与“保存到相册”是两个独立动作。后者通过 Kotlin 调用 MediaStore，把视频保存到“杰速口播”相册。

## 3. 云端数据库如何组织数据

### 3.1 核心业务表

| 表 | 主要字段或内容 | 用途 |
|---|---|---|
| `users` | user_id、email、password_hash、status | 用户账号与状态 |
| `devices` | device_id、user_id、device_fingerprint、access_token、revoked_at | 设备会话、令牌与撤销状态 |
| `email_login_codes` | 邮箱、验证码、有效期、尝试次数、消费状态 | 注册、登录等邮箱验证流程 |
| `credit_wallets` | bonus_balance、paid_balance、frozen_bonus、frozen_paid | 赠送点数、付费点数及冻结额度 |
| `credit_holds` | hold_id、user_id、job_id、total_points、status | 一次任务对应的冻结与结算记录 |
| `credit_ledger` | event_type、points、source、job_id、hold_id | 点数变动流水 |
| `render_jobs` | job_id、user_id、job_type、status、payload_json、result_json、worker_id、progress_percent | 任务参数、状态、结果与执行者 |
| `job_assets` | asset_id、job_id、user_id、kind、cos_key、file_size_bytes、status、expires_at | 素材和成品的文件索引与生命周期 |
| `job_events` | job_id、event_type、message、created_at | 上传、领取、完成、失败等事件 |
| `worker_nodes` / `worker_heartbeats` | worker_id、status、current_job_id、updated_at | 计算节点状态与心跳 |
| `douyin_transcriptions` | user_id、share_url、status、transcript、error_message | 抖音链接文案提取的独立任务记录 |

共享后端还保留授权等数据表；安卓用户界面无需手动输入激活码。

### 3.2 数据之间的逻辑关系

```text
用户 users
 ├─ 设备会话 devices
 ├─ 点数钱包 credit_wallets
 ├─ 点数流水 credit_ledger
 └─ 任务 render_jobs
     ├─ 输入素材与输出文件索引 job_assets
     ├─ 执行事件 job_events
     ├─ 点数冻结记录 credit_holds（计费任务）
     └─ 领取任务的 worker_id
```

这是业务上的关联关系，不意味着每条关联都由数据库外键约束实现。

`render_jobs` 中既有视频生成任务，也有预处理任务。文案、参数等可变内容放入 JSON 字段，任务状态、用户归属、时间和计费信息使用单独字段，方便查询和调度。

### 3.3 文件与索引分离

数据库保存“谁的文件、属于哪个任务、什么类型、存在哪里、是否过期”等信息，视频字节本身保存到 COS。

例如，一条素材记录可以表示：用户 U 的任务 J 使用人物视频 A，它在 COS 中的对象键为 `inputs/U/J/A/avatar.mp4`。

`cos_key` 是对象的存储标识；上传、下载时使用服务端生成的临时签名 URL。签名 URL 过期与文件被删除是两件事：只要对象仍存在且权限允许，就可以重新申请下载地址。

## 4. 从启动到成片的完整流程

### 第一步：启动与登录恢复

1. 应用初始化 Flutter 和播放器，安卓端选择云端生成模式。
2. 读取本地配置、安全存储中的令牌及应用版本。
3. 已登录时查询账号、钱包、点数流水和云端任务列表。
4. 未登录时进入注册或登录界面；注册、密码登录使用 `/api/mobile/auth/...` 接口。
5. 服务端维护用户和设备会话，后续业务请求携带令牌。

注册/登录是移动端专用入口，任务、素材、钱包等很多业务接口仍复用 `/api/client/...`。

### 第二步：准备文案

用户可以直接填写口播文案，或使用提取、改写能力。

- 纯文本改写可以由云端控制中心直接请求 DeepSeek API。
- 音视频提取文案按具体入口执行转写流程，相关生成引擎使用 faster-whisper。
- 抖音链接提取有独立的转写记录及查询接口。

因此，“改写文案”不一定需要等待 AutoDL GPU；是否走任务队列由具体操作决定。

### 第三步：克隆声音并试听

用户选择参考声音，提交文案和声音素材。需要 GPU 的声音任务经预处理任务链路交给 Worker，调用 CosyVoice 生成音频，结果上传到 COS，再由手机取得结果并下载试听。

当前安卓流程会先完成声音生成，再允许提交数字人视频。客户端还会检查生成声音是否对应当前文案，避免文案改动后继续使用旧配音。

### 第四步：配置画面和成片素材

选择人物形象视频，并按需设置字幕、BGM、封面模板和封面文字。安卓分支包含内置 BGM，也支持自定义素材。

这些设置进入任务参数；需要传输的文件作为任务素材登记。

### 第五步：创建上传会话并上传文件

```text
手机 → 控制中心：申请 upload-session，提交素材清单
控制中心 → 数据库：创建 uploading 任务和 pending 素材记录
控制中心 → 手机：返回 job_id、asset_id、签名上传地址
手机 → COS：流式上传文件
手机 → 控制中心：逐个回报 uploaded
控制中心 → 数据库：更新素材上传状态
```

典型素材包括人物视频、已生成的配音，以及所需 BGM、封面等。创建上传会话与正式提交生成任务是分开的，上传中的任务不会立即开始 GPU 生成。

### 第六步：正式提交任务并冻结点数

手机调用 `/api/client/jobs/{job_id}/submit`。

服务端检查任务归属、任务当前状态、素材上传状态、时长、排队限制和点数余额，然后在数据库事务内完成钱包更新、冻结记录、点数流水及任务入队。

当前钱包会把本次需要的点数从可用余额移入冻结额度；任务状态从 `uploading` 变为 `queued`。客户端显示的估价不直接决定最终记账，结算由服务端控制。

### 第七步：Worker 领取与执行

AutoDL Worker 主动调用 `/api/worker/claim-job`。数据库按优先级、创建时间等条件选择待执行任务，并把任务从 `queued` 改为 `running`，记录领取者。

Worker 随后下载 COS 素材并执行生成：

```text
下载人物视频和已生成配音
  → HeyGem 生成口型视频
  → 按任务配置完成字幕、BGM、封面等处理
  → FFmpeg 输出 MP4
  → 上传 COS
  → 向控制中心回报结果
```

若任务包含需要重新生成的声音或转写操作，则按对应任务类型调用 CosyVoice、faster-whisper 等能力。并非每次成片都重新跑一遍所有模型。

### 第八步：手机查询进度

手机主要通过 HTTP 轮询获取任务状态，云端视频任务轮询间隔为约 3 秒。

Worker 上报进度后，控制中心更新数据库；手机下一次查询读取新的状态、百分比和消息，再刷新 Flutter 页面。

任务正式提交并持久化后，退出应用不等于取消云端任务。再次进入可以查询历史任务；未完成的本地上传则不能据此保证会在后台继续。

### 第九步：任务完成与计费结算

Worker 上传结果并回报成功后，服务端把任务设为 `completed`，保存结果 JSON 和输出文件索引，结算被冻结的点数，并写入完成事件。

正常失败时，服务端保存错误信息，将任务设为 `failed`，释放对应冻结点数。

取消也由服务端处理：尚未开始的排队任务取消会释放冻结额度；当前代码对运行中的视频任务取消收取冻结额度的 30%，其余释放。这个规则属于当前实现，不能把所有取消都理解为全额退回。

### 第十步：下载、预览和保存相册

1. 手机从任务下载接口获取临时下载地址。
2. 流式下载到独立临时文件，显示下载进度。
3. 检查接收字节数、响应声明的文件长度和基本媒体格式。
4. 验证通过后将临时文件改名为正式本地文件。
5. 使用 media_kit 预览。
6. 用户点击保存时，通过 MethodChannel 调用 Kotlin 的 `saveVideo`，写入手机相册。

下载流程包含并发复用与独立临时文件处理，降低预览、自动下载等操作同时触发时互相覆盖文件的风险。这些检查不等于对整个视频做了完整逐帧解码验证。

## 5. 任务与文件的生命周期

```text
uploading → queued → running → completed
     └────────┴────────┴────→ canceled（按状态处理）
                       └───→ failed
```

上图展示视频任务的主要状态；后台还会处理上传、排队和执行超时等异常。

任务状态与文件状态分别维护：任务完成后，输出文件可能尚未下载；手机已下载后，云端仍可能保留副本；副本过期清理后，任务历史仍可能存在。

下载确认接口会记录下载情况，并安排延迟清理。当前服务端至少保留一小时，具体延迟由配置决定，不是确认后马上删除。后台 Scheduler 处理到期资源和异常任务。

因此，任务显示“已完成”、应用内可以预览、手机相册已有视频，分别代表三个不同阶段。

## 6. 代码入口

以下路径均指 `Android` 分支中的文件：

| 路径 | 内容 |
|---|---|
| `apps/client/lib/main.dart` | 登录恢复、接口调用、上传、任务轮询、下载及共享业务状态 |
| `apps/client/lib/mobile.dart` | 安卓页面、模板/BGM 选择、预览与保存相册入口 |
| `apps/client/android/app/src/main/kotlin/com/jiesu/oral_video_agent_client/MainActivity.kt` | 原生安全存储、MediaStore 保存、APK 安装 |
| `services/cloud/app/main.py` | 认证、素材、任务、下载和 Worker API |
| `services/cloud/app/store.py` | 数据表、任务状态、钱包与结算、任务领取 |
| `services/cloud/app/object_storage.py` | COS 对象操作与签名地址 |
| `services/cloud/app/redis_state.py` | 限流和辅助队列状态 |
| `services/cloud/app/scheduler.py` | 超时处理和资源清理 |
| `services/cloud/worker/autodl_worker.py` | Worker 领取、下载、执行、上传与回报 |
| `services/cloud/worker/run_render.py` | 具体生成任务与模型调用 |
