# 前端演示优先的全栈开发设计

日期：2026-08-20

状态：REVIEW_READY

占位品牌：MOSAIC

视觉方向：A / Editorial Instrument

## 1. 决策摘要

项目进入开发阶段，但交付顺序采用“前端演示优先”，而不是四种模态的真实后端并行开发。

首个里程碑交付一个可完整操作、可刷新恢复、具有高保真视觉和可信状态变化的内部演示产品。工程从第一天建立真实的前后端目录、共享契约和 Adapter 边界；前端先连接 Demo Adapter，组织内部评审通过后再把相同接口切换到真实 Platform API。

这不是静态 HTML、线框图或一次性原型。演示版必须具备完整路由、响应式布局、状态循环、动效、演示数据持久化、错误状态、自动化测试和视觉回归基线。

当前开发主线不包含临时公网 Ollama 调用验证。既有 Ollama 文档保留，但不作为本阶段依赖、Gate 或验收证据。

## 2. 与总产品设计的关系

本设计是 `docs/product-design.md` 的阶段性执行补充。

保留的总设计原则：

- 用户先选择模型，再进入适合该模型能力的工作台。
- 文本对话与图片、视频、音频生成采用不同交互模型。
- 前端不感知 Provider 密钥、Base URL 和供应商私有请求格式。
- 产品模型身份、实际模型 revision、deployment 和 Provider 映射分离。
- 会话、任务、资产和用量在产品层有稳定身份。

本设计覆盖并调整的内容：

- 把高保真前端、完整页面和内部演示提前为第一个可交付里程碑。
- 第一个里程碑使用可审计的演示数据，不声称已经调用真实模型。
- 后端只交付可运行骨架、共享契约和健康边界，不在前端评审前实现完整账本、Saga、Provider 和对象存储链路。
- 真实 Provider 资格、Gate 0、Gate 0.5 和后续后端 Gate 仍需执行，但不阻塞前端演示。

## 3. 产品目标与受众

### 3.1 目标

让组织内部成员通过一个接近正式产品的高保真 Web 应用，直观评审：

- 模型发现方式是否清楚。
- 文本和媒体工作台的区分是否合理。
- 产品视觉是否达到专业 AIGC 工具的标准。
- 任务、生成记录、点数和状态表达是否容易理解。
- 哪些功能应在真实后端开发前增加、删除或重排。

### 3.2 主要受众

- 公司决策层和投资相关人员。
- 产品、设计、工程和基础设施团队。
- 受邀的潜在客户或渠道合作方。

### 3.3 演示真实性边界

- 演示环境在账户区域显示“内部演示”标识。
- 模型输出、用量、余额和任务耗时均为版本化演示场景数据。
- 演示环境不出现“已真实接入”“已部署到数据中心”或生产 SLA 等表述。
- 失败、退款和任务恢复不是静态截图，而是由 Demo Service 驱动的可重复状态变化。
- 任何模型名称、能力和价格在真实接入前都不构成 Provider 可用性承诺。
- 工程证据使用三个明确状态：`demo_scaffolding` 表示模拟行为，`provider_unverified` 表示接口或模型待资格验证，`observed_accepted` 只用于已有真实调用和验收证据的行为。

## 4. 模型展示规则

### 4.1 用户可见规则

前端只展示用户需要理解的产品名称、任务能力、适用场景、输入输出和可用状态。

前端不展示：

- 开源、闭源、开放权重等许可标签。
- 参数规模、量化格式、精度或“满血版”描述。
- Provider 名称、Provider 模型 ID、区域或日期快照。
- 数据中心部署细节。

参数规模不是量化版本。不同参数规模可能是能力不同的独立模型，但本产品选择在用户界面折叠为稳定的产品模型名称；后台仍必须固定真实 revision 和 deployment，不能因为前端隐藏而失去审计能力。

### 4.2 首批演示目录

文本与多模态理解：

- Qwen 3.5
- DeepSeek V4
- GLM 5.2
- Kimi K2.7 Code
- GPT-OSS
- Gemma 4

图片：

- Qwen Image
- FLUX 2

视频：

- HunyuanVideo 1.5

音频：

- Qwen3-TTS 1.7B VoiceDesign
- Qwen3-TTS 1.7B CustomVoice
- Qwen3-TTS 1.7B Base

### 4.3 内部模型对象

用户可见的 `ProductModel` 与内部执行配置分离：

```text
ProductModel
  -> ModelRevision
      -> Deployment
          -> ProviderConfig
```

演示阶段也保留这四层数据形状，但 Deployment 目标为 `demo`。未来真实 API 接入只增加 deployment 和 routing，不修改页面所依赖的 ProductModel 身份。

面向前端的模型目录对象只包含：

```text
product_model_id
display_name
category
task_type
description
capabilities
input_schema
availability
pricing_summary
```

该对象不返回 `provider`、`provider_model_id`、`quantization`、`license`、`snapshot_date`、`deployment_id` 等内部字段。

## 5. 视觉系统

### 5.1 Design Read

这是面向内部决策者和专业创作者的 B2B AIGC 产品。视觉采用明亮、编辑式、精密工具语言，强调成熟产品结构与视觉记忆点，不使用通用 AI 紫色渐变模板。

### 5.2 视觉参数

| 表面 | Design Variance | Motion Intensity | Visual Density |
|---|---:|---:|---:|
| 公开产品页 | 8 | 6 | 3 |
| 模型广场 | 6 | 4 | 5 |
| 生成工作台 | 5 | 4 | 6 |
| 对话、记录与用量 | 4 | 3 | 7 |

### 5.3 基础 Token

| Token | 值 | 用途 |
|---|---|---|
| `canvas` | `#F5F6F8` | 页面画布 |
| `surface` | `#FFFFFF` | 主表面 |
| `surface-muted` | `#ECEFF3` | 次级分区 |
| `ink` | `#15171A` | 主文字 |
| `ink-muted` | `#667085` | 次级文字 |
| `line` | `#D7DCE3` | 边界和分隔 |
| `accent` | `#2F5BEA` | 唯一品牌强调色 |
| `danger` | `#C63C45` | 语义错误色，仅用于错误 |
| `warning` | `#A66616` | 语义警告色，仅用于警告 |
| `success` | `#227A53` | 语义成功色，仅用于状态 |

语义状态色不作为第二品牌强调色。所有普通主要动作统一使用 `accent`。

### 5.4 字体与数字

- 拉丁文字和数字使用 Geist Sans / Geist Mono。
- 中文使用 Noto Sans SC，并提供系统中文无衬线回退。
- 主标题保持两行以内，使用紧凑字距和清晰字重差。
- 余额、用量、时长、Token 和任务 ID 使用 tabular numbers。
- 不用随机衬线字体制造“高级感”。

### 5.5 形状与材质

- 页面和主要工作区使用近乎平面的层级，不给所有内容套卡片。
- 卡片圆角 12px，输入控件 8px，媒体容器 10px，按钮 8px；只有筛选 Chip 可以使用全圆角。
- 阴影只用于浮层和真正的层级变化，普通卡片使用 1px 边框和背景层级。
- 不使用外发光、漂浮球体、全页玻璃拟态或深色宇宙背景。

### 5.6 动效

- 页面进入、区域切换和列表重排使用 Motion。
- 普通交互时长 180-240ms，页面级编排 280-420ms。
- 只动画 transform 和 opacity。
- 卡片 hover 用轻微位移、边界强调或图片裁切变化，不用统一放大所有卡片。
- 流式文本、任务状态和余额变化的动画必须表达真实状态变化。
- 全部动效支持 `prefers-reduced-motion` 静态降级。

### 5.7 设计交付物

- `docs/DESIGN.md`：颜色、字体、字号、间距、栅格、圆角、边框、状态色、动效和响应式规则的唯一设计基线。
- 公开页、模型广场、文本工作台和视频工作台的桌面视觉证据。
- 模型广场、文本工作台和媒体工作台的移动视觉证据。
- Loading、Empty、Error、Offline、Unauthorized 和任务状态的组件证据。
- MOSAIC 品牌名只从集中配置读取，页面组件不得写死品牌字符串。

## 6. 信息架构与页面范围

### 6.1 公开区域

- `/`：产品介绍页，展示产品定位、四类能力、工作台预览、自有算力迁移叙事和商务入口。
- `/login`：邀请制账户登录演示，包含首次登录必须修改密码的演示状态。

### 6.2 登录后区域

- `/models`：模型广场，支持分类、搜索、精选和模型详情抽屉。
- `/chat/[conversationId]`：文本对话、历史会话、流式生成和重新生成。
- `/studio/image/[modelId]`：图片生成工作台。
- `/studio/video/[modelId]`：视频生成工作台。
- `/studio/audio/[modelId]`：音频生成工作台。
- `/generations`：统一生成记录。
- `/generations/[jobId]`：任务详情、状态时间线、输入摘要、结果和用量。
- `/usage`：余额、预留、结算、退款和模型维度用量。
- `/account/security`：最小安全入口，演示修改密码、查看当前会话、撤销其他会话和退出登录；不扩展为完整账户设置中心。

### 6.3 必须覆盖的页面状态

- Loading
- Empty
- Partial availability
- Error
- Offline
- Unauthorized
- Insufficient balance
- Provider timeout 演示状态
- Content rejected 演示状态
- Queued / Running / Storing / Succeeded / Failed / Canceled

## 7. 关键演示流程

### 7.1 模型发现

用户登录后进入模型广场，按文本、图片、视频和音频筛选。模型卡片展示名称、能力、场景和主动作，不展示底层部署信息。

首次登录场景先进入受限状态，用户完成演示密码修改后才能进入模型广场。账户菜单始终提供安全入口和退出登录。

### 7.2 文本对话

用户进入 Qwen 3.5 或 DeepSeek V4，完成两轮上下文相关对话。Demo Service 按确定性脚本推送分段文本，支持停止、重新生成、复制、会话切换和刷新恢复。

### 7.3 图片生成

用户选择 Qwen Image 或 FLUX 2，提交提示词和画面参数。任务从排队进入生成和完成，结果写入统一生成记录。

### 7.4 视频生成

用户选择 HunyuanVideo 1.5，选择演示素材、提交任务、离开页面再返回，任务继续推进。演示包含一次成功和一次失败退款场景。

### 7.5 音频生成

三个 Qwen3-TTS 工作台共享音频任务底座，但根据 VoiceDesign、CustomVoice 和 Base 显示不同输入控件和帮助信息。生成结果可播放、下载并出现在用量中心。

### 7.6 用量闭环

每次演示请求生成唯一请求 ID、预留记录和最终结算记录。余额、生成记录和任务详情共享同一演示状态源，不能各页面写死不同数字。

## 8. 全栈工程架构

### 8.1 技术栈

前端：

- Next.js App Router
- TypeScript strict mode
- Tailwind CSS v4
- Radix Primitives，按 MOSAIC Token 深度定制，不使用默认主题外观
- Motion
- Phosphor Icons
- Vitest、Testing Library、Playwright 和 axe

后端骨架：

- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL
- S3 兼容对象存储接口
- pytest

工程：

- pnpm workspace 管理 Web 与共享 TypeScript 包。
- Python API 使用 `pyproject.toml` 和锁文件管理依赖。
- Docker Compose 提供本地 PostgreSQL 和后续对象存储。

### 8.2 推荐目录

```text
apps/
  web/
    src/app/
    src/features/
    src/entities/
    src/shared/
    src/services/
  api/
    app/api/
    app/domain/
    app/adapters/
    app/infrastructure/
    tests/
packages/
  contracts/
  design-tokens/
infra/
  compose/
docs/
```

### 8.3 前端依赖方向

```text
app routes
  -> features
      -> entities + shared UI
      -> service interfaces
          -> demo adapters OR API adapters
```

禁止：

- 页面组件直接 import 演示 JSON。
- 模型卡片直接写 Provider 模型 ID。
- Chat、Image、Video、Audio 各自维护不同余额。
- UI 组件调用 `fetch`。
- shared 层反向依赖具体 feature。
- 通过全局 Store 保存所有局部表单状态。

### 8.4 Service 接口

前端通过以下接口访问数据：

- `AuthService`
- `ModelCatalogService`
- `ConversationService`
- `GenerationService`
- `AssetService`
- `UsageService`

每个接口有两个实现：

- `Demo*Service`：首个里程碑使用，读取版本化场景并持久化演示状态。
- `Api*Service`：真实后端接入时使用，遵循相同领域对象和错误语义。

Adapter 由应用根配置选择，feature 不判断当前是 demo 还是真实 API。

### 8.5 演示状态

- 使用一个版本化 `DemoScenario` 定义账户、模型、会话、任务、资产和账本初始状态。
- 使用 `DemoStateStore` 持久化到浏览器存储，带 schema version 和一键重置。
- 时间推进、流式文本和任务状态由可取消的 scheduler 驱动。
- Playwright 可以使用固定随机种子和虚拟时间得到可重复结果。
- 演示数据变更必须通过 service 领域操作，页面不能直接改 Store。

### 8.6 后端骨架边界

首个里程碑后端只需要：

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- OpenAPI 基础配置和统一错误结构
- 契约包生成或校验入口
- 数据库迁移与连接探测

首个里程碑不实现真实登录、Provider 调用、点数结算、对象上传和媒体 Worker。它们在内部前端评审后按独立后端计划交付。

## 9. 组件边界

### 9.1 共享基础组件

- AppShell
- NavigationRail
- TopBar
- Button / IconButton
- Input / Textarea / Select / Slider
- Dialog / Drawer / Popover / Tooltip
- EmptyState / ErrorState / Skeleton
- StatusBadge
- MediaFrame
- Amount / UsageMetric

### 9.2 领域组件

- ModelCard / ModelDetail
- ConversationList / MessageList / Composer / StreamResponse
- GenerationForm / JobProgress / OutputGallery
- AudioPlayer / VideoPlayer
- GenerationRecord / JobTimeline
- BalanceSummary / UsageLedger

领域组件依赖共享组件和领域类型；共享组件不知道模型、任务和账本概念。

## 10. 错误与状态规则

- 所有演示错误使用与未来 Platform API 相同的错误码形状。
- Error State 必须提供恢复动作，不能只显示红字。
- 页面刷新后非终态任务继续推进或恢复到脚本定义的状态。
- 重复点击提交使用客户端幂等键返回同一演示任务。
- 余额不足在生成前阻止请求。
- 删除和重置需要确认；重置只重置演示状态，不删除应用配置。
- 网络离线时保留未发送的文本和表单内容。

## 11. 响应式与可访问性

- 桌面为主要演示目标，基准视口为 1440x900 和 1728x1117。
- 1024px 以下将导航收起为紧凑模式。
- 768px 以下所有非对称工作台明确折叠为单列，生成表单和结果通过 Tab 或顺序布局呈现。
- 点击目标不小于 44x44px。
- 键盘可以完成导航、模型选择、消息发送和任务提交。
- 焦点样式清晰；状态不能只依赖颜色。
- 普通文字满足 WCAG AA；动效支持 reduced motion。

## 12. 测试与质量 Gate

### 12.1 自动化

- ESLint、TypeScript typecheck 和构建零错误。
- Design Token、Service 和状态转换单元测试。
- React Testing Library 覆盖关键表单和状态组件。
- Playwright 覆盖登录、模型筛选、两轮对话、图片生成、视频失败退款、音频播放和用量联动。
- axe 扫描关键页面无严重或高等级问题。

### 12.2 视觉验收

- 公开页、模型广场、文本工作台和视频工作台进行桌面截图评审。
- 模型广场、文本工作台和媒体工作台进行移动截图评审。
- 页面不得出现 AI 紫蓝渐变、三等分通用卡片、无意义玻璃拟态和重复布局。
- 公开页至少包含真实或生成的高质量视觉资产，不用 div 拼接的假截图。
- 所有 Loading、Empty、Error 和非终态任务状态都有设计完成度。

### 12.3 性能

- LCP 目标小于 2.5 秒。
- INP 目标小于 200ms。
- CLS 目标小于 0.1。
- 非首屏媒体和复杂工作台按路由懒加载。
- 动效不使用 React state 逐帧更新。

## 13. 交付分解

本项目不能用一个覆盖全部产品与后端的超大实施计划执行。后续拆成四份可独立验收的计划：

1. 工程基础、Design Token、共享组件和产品 Shell。
2. 模型广场、文本对话和统一演示状态。
3. 图片、视频、音频工作台、生成记录和用量中心。
4. 内部评审修订后，真实后端纵切与 Demo Adapter 替换。

前一计划必须产出可运行、可测试的软件，不以“文件已创建”作为完成标准。

## 14. 明确排除

首个前端演示里程碑不包含：

- 真实 Provider 或数据中心推理调用。
- 临时公网 Ollama 测试。
- 真实注册、密码找回和第三方登录。
- 真实支付、充值、订单和发票。
- 管理后台和完整运营 CLI。
- 智能体、工具调用和 ComfyUI 工作流。
- 聊天消息附件上传。
- 真实上传任意用户文件；视频首帧和媒体任务输入属于必要任务素材，但演示阶段只允许从预置素材库选择或进行不上传服务器的本地安全预览。
- 对自有算力性能、成本、并发或 SLA 的承诺。

## 15. 规格通过条件

设计规格获得批准后，实施计划必须满足：

- 先建立完整工程和解耦契约，再实现页面。
- 前端演示优先，但不牺牲代码结构、测试和后续 API 替换能力。
- A / Editorial Instrument 是唯一视觉方向。
- MOSAIC 是集中配置的开发占位品牌。
- 用户界面采用简化模型名和三个独立 Qwen3-TTS 工作台。
- 不展示开源、闭源、参数量、量化、满血版、Provider 或日期快照。
- 任何演示状态都来自统一 Service 和状态源。
- 当前阶段不执行 Ollama 公网验证。
