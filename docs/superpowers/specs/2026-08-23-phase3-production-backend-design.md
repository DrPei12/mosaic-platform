# MOSAIC 第三阶段：面向外部租户的生产后端设计

日期：2026-08-23

状态：APPROVED FOR IMPLEMENTATION

阶段：Phase 3 / Production Product Direction

## 1. 目标与非目标

本阶段把 MOSAIC 从“浏览器内前端演示”升级为可承载真实客户、真实账号、真实模型调用和真实用量记录的产品骨架。首条生产纵切必须完成：

> 注册/登录 → 进入租户 → 获取真实可用模型目录 → 创建文本会话 → 调用百炼真实模型 → 流式返回 → PostgreSQL 持久化 → 记录用量与账本事实。

图片、视频和音频不伪装成同步文本接口，使用统一业务任务模型和各自真实的 Provider 协议。四个模态都必须有一次真实上游 smoke 作为接入验收；单元测试中的 test double 只验证错误、超时、幂等和并发分支，不能替代 live gate。

本阶段不包含 Ollama 公网调用，也不为不存在或未验证的模型创建“可用”状态。

## 2. 已确认事实与需要纠正的旧前提

### 已确认

- 当前 FastAPI 只实现 `/api/v1/health/live` 和 `/api/v1/health/ready`，真实 auth、catalog、conversation 与 generation API 尚不存在。
- 当前 Web 在环境变量未配置时会静默选择 Demo Adapter；这在生产分支属于 fail-open，必须改为 API 默认、Demo 显式启用。
- 当前 API Catalog Adapter 依赖 `DEMO_SCENARIO` 的模型 ID 和展示元数据，真实后端返回新模型会被拒绝。
- 百炼文本模型可以走 OpenAI-compatible Chat Completions；Qwen Image、Wan 视频和 Qwen3-TTS 使用 DashScope 原生 HTTP 协议。视频生成是创建任务后轮询的异步流程。
- 百炼生成的图片、视频和音频 URL 只有短期有效期，生产系统拿到结果后必须立即转存到自己的对象存储。

### 纠正

- “Provider 兼容 OpenAI”不等于所有模态都兼容 OpenAI。统一的是 MOSAIC 内部业务接口，不是强行统一上游报文。
- “模型广场里有名称”不等于该模型已可调用。生产目录只能把已经配置路由且 live probe 通过的模型标为 `available`。
- API Key 足以用于当前通用 DashScope 域名开发，但生产高并发还需要百炼业务空间专属域名。专属域名需要 Workspace ID；目前尚未取得，因此不能把通用域名的本地验证描述成最终生产网络配置。

## 3. 技术架构

采用“模块化单体 API + 独立 Worker”的结构，而不是一开始拆成大量微服务：

```text
Next.js Web
    │ same-origin /api/v1
    ▼
FastAPI API
    ├─ Identity & Tenant
    ├─ Model Catalog & Routing
    ├─ Conversation & Generation
    ├─ Usage, Reservation & Ledger
    ├─ Provider Gateway
    └─ Transactional Outbox
          │
          ▼
RabbitMQ ──► Celery media workers
                  │
                  ├─ Bailian text/image/video/audio
                  └─ S3-compatible object storage

PostgreSQL = 业务事实源
Redis      = 限流、租约、短期缓存和并发协调
```

API 与 Worker 可以独立扩容，但共享领域模型和 Provider 适配器。只有当团队规模、发布频率或负载证明需要时再拆服务。

## 4. 模块边界

### 4.1 Identity & Tenant

- 原生邮箱/密码认证，不依赖 OIDC/SSO。
- 密码使用 Argon2id；绝不保存明文或可逆密码。
- 浏览器使用随机、不可预测的 opaque session token。数据库只保存 token 哈希；Cookie 使用 `HttpOnly`、`Secure`、`SameSite=Lax`。
- 所有写请求使用 CSRF token；登录、注册、重置密码按 IP、账号和设备指纹做分层限流。
- 用户与租户通过 membership 关联，角色首批为 `owner`、`admin`、`member`、`billing_viewer`。
- 所有业务查询都必须从认证上下文取得 `tenant_id`，禁止接受客户端传入的 tenant 作为授权依据。

### 4.2 Model Catalog & Routing

公开模型对象只包含产品信息，不泄露 Provider、部署、密钥、内部 model ID 或路由优先级。

内部使用三层映射：

```text
ProductModel（用户看到什么）
    → ModelDeployment（实际可调用能力）
        → ProviderEndpoint（调用到哪里）
```

一个产品模型可以有多条部署，但首期只允许显式主路由，不做未经验证的“自动换模型”。同一模型的 Provider 故障可切到同一模型的备用部署；不能把 HunyuanVideo 自动替换成 Wan 并仍向用户声称是 HunyuanVideo。

首批真实路由：

| 公开产品 | 内部 Provider model ID | 模态 | 接入协议 |
|---|---|---|---|
| Qwen 3.5 Plus | `qwen3.5-plus` | 文本 | OpenAI-compatible Chat Completions |
| Qwen Image 3.0 Pro | `qwen-image-3.0-pro` | 图片 | DashScope multimodal generation |
| Wan 2.7 | `wan2.7-t2v` | 视频 | DashScope async video synthesis |
| Qwen3-TTS Flash | `qwen3-tts-flash` | 音频 | DashScope multimodal generation |
| Qwen3-TTS 1.7B VoiceDesign | `qwen3-tts-vd-2026-01-26` | 音频 | DashScope voice customization + TTS |
| Qwen3-TTS 1.7B CustomVoice | `qwen3-tts-vc-2026-01-22` | 音频 | DashScope voice customization + TTS |

带日期的 Provider ID 只存在于内部路由，不在用户界面展示。声音设计与声音复刻还需要先创建租户隔离的 voice resource；没有 voice resource 时不得伪装成可直接生成。
`Qwen3-TTS 1.7B Base` 继续作为独立产品展示，但在找到并验证它的精确 Provider 路由前保持不可用；禁止把 `qwen3-tts-flash` 冒充为 Base。

### 4.3 Provider Gateway

内部定义四类端口：

- `TextGenerationProvider`：complete、stream。
- `ImageGenerationProvider`：submit/generate、result。
- `VideoGenerationProvider`：submit、poll、cancel-if-supported。
- `SpeechGenerationProvider`：synthesize，以及后续 voice design/clone resource。

Provider Adapter 负责协议转换、超时、错误归一、Provider request ID、用量解析和结果 URL 提取。它不负责租户权限、余额或业务幂等。

安全要求：

- `DASHSCOPE_API_KEY` 只从进程环境或生产 Secret Manager 读取，不读取仓库 `.env`，不写数据库，不进入客户端 bundle。
- 日志禁止记录 Authorization、Cookie、原始上游 body 和完整 prompt；错误只返回 MOSAIC code、request ID 与可重试标记。
- Provider base URL 是受控部署配置，外部租户不能提交任意 URL，避免 SSRF。
- 对可能收费的 POST 不做盲目自动重试；先靠 MOSAIC idempotency record 判定是否已经提交。查询任务等幂等 GET 才做有界退避。

### 4.4 Conversation & Generation

文本请求沿用 Phase 2 的 SSE 公共契约：`started → delta* → completed|stopped|failed`，sequence 严格单调，一个请求只能有一个终态。

媒体使用统一 `generation_job` 状态机：

```text
accepted → reserved → queued → submitted → running
                                      ├─ succeeded
                                      ├─ failed
                                      ├─ cancelled
                                      └─ expired
```

状态迁移使用数据库 compare-and-set；Worker 重复投递不会重复计费或重复写结果。Provider 已提交但本地超时属于 `submitted_unknown` 类别，必须先按 Provider task ID 对账，不能直接再次提交。

### 4.5 Usage, Reservation & Ledger

余额不是一个可以直接覆盖的数字，而是账本投影：

- 提交前按最坏可接受上限创建 reservation。
- Provider 返回实际 usage 后结算 reservation，并写不可变 ledger entries。
- 失败或取消释放未使用预留。
- `usage_record` 保存 Provider 原始计量维度的规范化副本、定价版本和 Provider request ID。
- `ledger_entry` 只追加，不 update/delete；余额是 entries 的汇总或可重建投影。
- 金额使用最小货币单位整数，token/字符/秒/图片数分别保存，禁止用浮点数保存金额。

首期可以使用人工充值/测试额度，不在没有支付通道前伪造在线支付。

## 5. PostgreSQL 核心数据模型

首批表：

- `tenants`
- `users`
- `memberships`
- `auth_sessions`
- `product_models`
- `provider_endpoints`
- `model_deployments`
- `tenant_model_entitlements`
- `conversations`
- `messages`
- `inference_requests`
- `generation_jobs`
- `generation_artifacts`
- `usage_records`
- `wallet_accounts`
- `balance_reservations`
- `ledger_entries`
- `idempotency_records`
- `outbox_events`
- `audit_events`

关键约束：

- 所有租户业务表含 `tenant_id`，外键尽量使用 `(tenant_id, id)` 组合保证跨租户引用在数据库层失败。
- 产品模型、Provider endpoint 和 deployment 是平台全局配置；租户通过 `tenant_model_entitlements` 获得使用权，避免复制密钥引用并确保部署并发上限可跨租户统一计算。
- `memberships (tenant_id, user_id)` 唯一。
- `idempotency_records (tenant_id, actor_id, operation, key)` 唯一，并保存 request hash；同 key 不同 payload 返回冲突。
- `inference_requests` 和 `generation_jobs` 分别保存 MOSAIC request ID 与 Provider request/task ID，后者在 Provider 范围内唯一。
- 账本使用双分录或至少平衡约束；任何业务表不得直接“减余额”。
- PostgreSQL RLS 作为第二道租户隔离边界；每个事务使用 `SET LOCAL app.tenant_id`，连接归还池前不残留上下文。

## 6. 并发、限流与幂等

并发不是“多开几个线程”，而是四层控制：

1. 边缘/API：请求大小、连接数、IP 与账号限流。
2. 租户：按套餐控制同时运行任务和每分钟配额。
3. 模型部署：按 Provider RPM/TPM/并发上限做 admission control。
4. Worker：不同模态独立队列，视频不能挤占文本和音频任务。

Redis 使用带 TTL 的租约型信号量，获取/续约/释放通过 Lua 原子执行；进程崩溃后租约自动过期。数据库仍保存最终 job 状态，Redis 不作为业务事实源。

RabbitMQ 消息采用 at-least-once，Consumer 必须幂等。API 事务只写业务表和 `outbox_events`；Outbox Relay 提交消息成功后再标记发布，避免“数据库提交了但消息没发”或反过来。

## 7. 对象存储与文件安全

- 使用 S3-compatible 接口；本地开发可用 MinIO，生产可用 OSS/S3。
- 上传通过短时 pre-signed URL，服务端记录 tenant、owner、content type、大小、checksum 和状态。
- 不信任客户端 MIME；Worker 下载后做格式探测、大小/时长/像素限制和恶意文件扫描。
- Provider 临时 URL 由 Worker 下载后转存，不直接长期暴露给客户。
- 租户下载 URL 短期签名，禁止公开 bucket。

## 8. 可观测性与运维

每次请求贯穿：`request_id`、`tenant_id`、`actor_id`、`job_id`、`deployment_id`、`provider_request_id`。prompt 内容默认不进入日志。

指标至少包含：

- API 延迟、错误率、SSE 中断率。
- 每租户和每部署的 admission reject、排队时间、运行时间。
- Provider 429/5xx/超时与费用。
- Outbox backlog、队列深度、重试次数、dead-letter。
- reservation 超时、账本不平衡、usage 对账差异。

`/ready` 检查 PostgreSQL、Redis、队列配置和 Provider 凭证配置；Provider 上游临时故障通过独立 dependency health 暴露，不让高频 readiness probe 产生收费调用。

## 9. API 路线

先满足现有前端契约，再新增媒体与账本：

- `/api/v1/auth/*`
- `/api/v1/models`
- `/api/v1/conversations/*`
- `/api/v1/generations`
- `/api/v1/generations/{job_id}`
- `/api/v1/uploads/*`
- `/api/v1/usage/*`
- `/api/v1/wallet/*`

内部管理 API 与外部客户 API 分离权限和路由前缀；Provider 配置、定价和模型上架不能暴露给普通租户。

## 10. 验收边界

一个能力只有同时满足以下条件才可标记为生产可用：

- 公开契约测试通过。
- 单元/集成测试覆盖成功、超时、限流、重复请求、跨租户拒绝和日志脱敏。
- 使用当前设备环境变量完成真实 Provider live smoke。
- 结果及 usage 写入 PostgreSQL，媒体结果已转存对象存储。
- 失败时没有 Demo fallback、没有静默换模型、没有重复扣费。

当前网络环境访问 `dashscope.aliyuncs.com` 时 TLS 握手被本机代理链路中断，因此 live smoke 暂未通过。该事实不能用 mock 或文档响应替代；实现可以继续，最终验收门禁保持失败，直到网络链路恢复并真实调用成功。

## 11. 官方资料

- 地域和接入域名：<https://help.aliyun.com/zh/model-studio/beijing-access-information>
- 文本 OpenAI-compatible 调用：<https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions>
- 图片生成：<https://help.aliyun.com/zh/model-studio/text-to-image>
- Wan 2.7 文生视频：<https://help.aliyun.com/zh/model-studio/text-to-video-api-reference>
- 非实时语音合成：<https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide>
