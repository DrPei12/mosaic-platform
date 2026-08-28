# Phase 2 Catalog and Chat Evidence

日期：2026-08-23
范围：MOSAIC Phase 2 前端演示优先的模型广场、文本对话、响应式几何、键盘和 axe 门禁。

## 边界声明

Design status: demo_scaffolding

Provider status: provider_unverified

Real model invocation: NOT_IMPLEMENTED_SCOPE

Server-side authorization: NOT_IMPLEMENTED_SCOPE

Real PostgreSQL business persistence: NOT_IMPLEMENTED_SCOPE

Balance/ledger: N/A_PHASE_3

目录、对话、停止、重新生成、刷新恢复和草稿行为均由浏览器 Demo Adapter 驱动。API conversation endpoints are adapters only/unverified；本证据不证明真实 Provider、服务端授权、PostgreSQL 业务持久化或余额/账本已经接入。

本次 Windows 证据使用系统 Chrome 回退（`C:\Program Files\Google\Chrome\Application\chrome.exe`），并以 `--disable-extensions` 启动隔离进程。该 Chrome fallback evidence boundary 只说明本机浏览器可执行 E2E，不扩展到其他机器、CI 浏览器或生产运行时。配置优先读取 `MOSAIC_E2E_BROWSER_EXECUTABLE`；不存在时仅在 Windows 检查标准 Chrome/Edge 路径，其他系统继续使用 Playwright bundled browser。

## 已观察的目录证据

- canonical model names：12 个，精确集合为 Qwen 3.5、DeepSeek V4、GLM 5.2、Kimi K2.7 Code、GPT-OSS、Gemma 4、Qwen Image、FLUX 2、HunyuanVideo 1.5、Qwen3-TTS 1.7B VoiceDesign、Qwen3-TTS 1.7B CustomVoice、Qwen3-TTS 1.7B Base。
- category counts：文本 6、图像 2、视频 1、音频 3。
- category/search intersection：文本 + `Qwen 3.5` 返回 1；不存在的搜索返回空态；清空搜索恢复文本 6。
- 收藏使用 `aria-pressed`，刷新后保留状态。
- 非 Hero Radix detail drawer 支持 Escape 并恢复触发控件焦点。
- 文本模型创建 `/chat/conversation-*` Demo 会话；图像/视频/音频 drawer CTA 分别进入 `/studio/image/qwen-image`、`/studio/video/hunyuan-video-1-5`、`/studio/audio/qwen3-tts-voice-design`。
- UI body 未观察到 Provider、deployment、revision、quantization、precision、license、snapshot 或 open-source 字样。

## 已观察的对话证据

- seeded Qwen 3.5 sessions：`conversation-qwen-3-5-001` 与 `conversation-qwen-3-5-002`，各包含稳定的双轮上下文脚本。
- 正常流式响应按可见 delta/status 等待，不使用 `waitForTimeout` 或 sleep。
- `演示停止响应`：第一段可见 delta 后停止，部分文本保留并显示停止态。
- 重新生成最新 assistant 不新增 user 消息。
- 首段 delta 可见后刷新，恢复从持久化 cursor 继续，终态无重复 chunk。
- offline 草稿：离线尝试发送不产生请求、草稿保留；恢复 online 并刷新后 Demo 草稿仍可见。

## 几何、无障碍和快照

- 项目：desktop 1440×900、wide 1728×1117、mobile 390×844、mobile-large 426×923。
- marketplace/chat 每个项目均执行 serious/critical axe 过滤，观察结果为 0；键盘路径覆盖分类、搜索、收藏、drawer Escape、会话切换、composer、发送、停止、重新生成和移动 drawer；reduced-motion 核心控件可用。
- 桌面 rail 观察为 240px，TopBar 80px；移动 TopBar 64px、底部导航基础高度 76px；chat conversation column 328px、header 80px、composer panel 104px；卡片 border 1px/radius 12px；模型标题 22/28；viewport 无横向溢出。
- 12 张 Windows snapshots 已使用 `--update-snapshots` 生成并逐张查看，之后使用不带 update 的正常截图门禁复验；不得将 update 参数作为正常 Gate。

## 可复核命令

```powershell
pnpm verify:web
uv run --project apps/api pytest -q
uv run --project apps/api ruff check apps/api/app apps/api/tests
uv run --project apps/api mypy apps/api/app apps/api/migrations
pnpm --filter @mosaic/web test:e2e
git diff --check
```

## 最终观察记录

- `pnpm verify:web`：web lint、typecheck、brand/boundary scans、contracts 49 tests、design-tokens 4 tests、web Vitest 207 tests、production build 均通过。
- `uv run --project apps/api pytest -q`：15 passed in 2.05s。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests`：All checks passed!
- `uv run --project apps/api mypy apps/api/app apps/api/migrations`：Success: no issues found in 13 source files。
- `pnpm --filter @mosaic/web test:e2e`：104 passed (3.9m)，retries=0，四个项目均通过。
- `git diff --check`：无输出、退出码 0。
- 截图更新后不带 `--update-snapshots` 的 marketplace/chat/shell 12-case 复验：12 passed (54.1s)；完整 E2E 也在不带 update 的正常命令下通过。

以上结果只证明当前 checkout 的前端 Demo 与 API health/rewrite 验证边界；不改变本文件的真实 Provider、授权、数据库和账本排除项。
