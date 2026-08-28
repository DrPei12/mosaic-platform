# MOSAIC 收口交接

交接日期：2026-08-27

来源分支：`codex/production-hardening`

最后一次四模态 Provider 证据绑定提交：`ba76f74980184927eecb151c8c874297594c5441`

## 结论

当前仓库已经形成可复现的 E0–E10 生产硬化代码基线，但不是可直接向真实客户收费开放的
production-ready 产品。硬化基线覆盖租户隔离、持久任务、原子计费、对象存储、队列、
Worker、可观测性、备份恢复和发布 Gate；商业支付、完整客户能力以及最终公开快照的
当前提交真实模型闭环仍未完成。

Provider 路由应保持 fail-closed。任何后续激活必须重新从待发布的干净提交生成签名证据，
不得复用本交接中记录的旧提交证据。

## 已确认基线

| 范围 | 已确认结果 | 证据边界 |
| --- | --- | --- |
| API 全量测试 | `360 passed, 4 skipped` | E0–E10 完整回归基线；4 项为需付费的 Provider 用例 |
| Web 单元测试 | `298 passed` | E0–E10 完整回归基线 |
| Contracts / design tokens | `52 passed` / `4 passed` | E0–E10 完整回归基线 |
| Playwright | `108 passed` | 四个响应式项目；主要验证确定性 UI/API 契约 |
| Ruff / mypy | PASS / 128 source files | E0–E10 完整回归基线 |
| Alembic | 单一 head `20260826_0013` | PostgreSQL 迁移基线 |
| PostgreSQL RLS | PASS | app/worker/owner 角色及跨租户测试通过 |
| 备份恢复 | PASS | PostgreSQL 逻辑备份、MinIO mirror、hash/head/object count 校验 |
| 运行时故障门禁 | PASS | media/video Worker 独立失联时 readiness 与请求准入均 fail-closed |
| 最终两处修复 | `47 passed`，Ruff/mypy PASS | 仅针对 generation repository/worker 的收口回归 |

完整记录见 [E10 integration receipt](docs/evidence/production-hardening-e10.md)。

## 真实模型证据

签名 Provider smoke 在提交 `ba76f74980184927eecb151c8c874297594c5441` 上真实通过：

| 能力 | 路由 | 结果 |
| --- | --- | --- |
| 文本 | `qwen3.5-plus` | 返回非空文本、Provider request ID 与 usage |
| 图片 | `qwen-image-3.0-pro` | 下载并校验 213,470 bytes |
| 视频 | `wan2.7-t2v` | 下载并校验 2,784,736 bytes |
| 语音 | `qwen3-tts-flash` | 下载并校验 180,524 bytes |

该证据同时绑定 catalog manifest、smoke script SHA-256、Git commit、时间窗口和 HMAC；
证据文件与 HMAC 密钥均位于 Git 树外，不随公共仓库发布。

真实全栈 smoke 在同一提交上确认文本聊天成功。随后图片闭环暴露两个事实：

1. API 接收结果映射曾因数据库生成的 `updated_at` 被异步延迟加载而返回 500；最终代码已在
   活跃事务内显式 refresh，并通过针对性回归。
2. 修复后的一次图片任务进入 `submitted_unknown`，另一次收到结构化
   `provider_http_error`；此次收口没有继续产生付费调用，也没有得到最终公开快照上的图片
   全链路成功证据。

因此，上表只能证明 `ba76f749…` 的四模态 Provider 适配器 smoke，不证明最终公开快照已通过
浏览器到 Provider、对象存储、计费和下载的当前提交闭环。

## 最终收口修复

- `apps/api/app/generations/repository.py`：在 reservation 外键更新后显式刷新 job，避免
  Async SQLAlchemy 在响应映射阶段触发隐式 IO。
- `apps/api/app/generations/worker.py`：记录脱敏、低基数的 Worker 异常事件，只保留
  worker、outcome、error code 与 HTTP status，不记录 Prompt、密钥或 Provider 响应正文。

## 尚未完成

以下项目是正式客户开放前的真实缺口，不得用 Mock、旧证据或 UI 展示代替：

1. 最终公开快照的当前提交六模型浏览器/API 全链路验收，尤其是图片任务失败原因与对象转存路径。
2. 至少三个可切换文本模型、统一版本化 capability schema 与模型感知上下文编排器。
3. System Prompt 版本管理、真实文件上下文、视觉输入、联网搜索及可核验引用。
4. 平台 API Key 的创建、轮换、限额、调用、统一计费与端到端示例。
5. 确定的支付渠道、回调签名、充值、退款和对账；当前 PTS 钱包/账本不是商业支付。
6. 全新用户无需人工改库完成完整客户旅程的当前提交浏览器验收。
7. 发布主机上的 Docker 镜像启动、不可变 digest、TLS、secret injection、容量与故障演练。

当前只有一个真实文本路由，不能声称已经满足多文本模型产品目标。

## 复现与接手

基础工具版本：Node.js 24、pnpm 11、Python 3.12、uv，以及 PostgreSQL、Redis、RabbitMQ
和 S3-compatible 对象存储。安装依赖后先执行：

```powershell
pnpm install --frozen-lockfile
uv sync --project apps/api --frozen
pnpm verify:api
pnpm verify:web
pnpm test:e2e
pwsh -NoProfile -File scripts/verify-release.ps1 -StaticOnly
```

真实 API 模式的依赖、迁移、账号创建、Worker 拓扑和 fail-closed 激活流程见
[本地运行手册](docs/runbooks/local-production-development.md)。公共仓库不包含演示密码；应使用
`apps/api/scripts/operator_accounts.py` 创建全新邀请账号并通过首次改密流程。

继续工作时应从以下顺序恢复：

1. 在隔离环境中启动全部依赖和 Worker，确认 readiness 与受保护 metrics。
2. 保持 Provider 路由禁用，先定位图片 `provider_http_error`，不得自动重试未知提交。
3. 在干净候选提交上显式确认付费调用，重新生成签名 Provider 证据。
4. 使用新用户跑完浏览器、API、数据库、队列、对象存储、计费的当前提交闭环。
5. 仅在所有必需 Gate 通过后生成 `PASS` receipt；缺少镜像或外部资源时只能是 `BOUNDED`。

## 公开仓库边界

`.runtime/`、`.release/`、`.env*`、Playwright 输出、真实 Provider evidence、运行时凭据和
本地演示账号凭据均被排除。仓库当前未选择开源许可证；公开可见不等于自动授予复制、修改或
再分发权利。

公共仓库采用不携带原 Git 对象的单提交源码快照。首个公开提交
`5745b8c0b4fd5b8374219a39470ef4ed935a8888` 是该公共仓库发布脚本的 ancestry baseline；
原本地来源提交记录在公开提交说明中。该打包基线只解决 Git 历史可达性，不改变上述真实模型
证据边界，也不会使非 live CI receipt 从 `BOUNDED` 变为 `PASS`。
