# MOSAIC 第二阶段：模型广场与文本对话设计

日期：2026-08-21

状态：APPROVED

阶段：前端演示优先 / Phase 2

## 1. 决策摘要

第二阶段把第一阶段的 Foundation Shell 替换为可用于组织内部评审的高保真模型广场和文本对话工作台。实现必须在视觉上对标用户批准的模型广场原型，并与新增的桌面对话、移动模型广场参考保持同一产品语言。

第二阶段继续使用 Demo Adapter，不调用真实 Provider，不展示真实余额，不声称模型已经部署到数据中心。用户能完成模型筛选、搜索、收藏、查看详情、进入文本模型、切换会话、两轮上下文对话、停止、重新生成和刷新恢复。

## 2. 视觉参考与优先级

参考文件：

- `docs/assets/phase2-model-marketplace-desktop.png`
- `docs/assets/phase2-chat-desktop.png`
- `docs/assets/phase2-model-marketplace-mobile.png`
- `docs/DESIGN.md`

优先级：

1. 用户批准的产品内容、模型名称和边界。
2. `docs/DESIGN.md` 的 Token 与无障碍规则。
3. 三张参考图的构图、层级、比例、材质和视觉节奏。
4. 实现可维护性与响应式约束。

参考图中的 `Mosaic Mind 7B`、`Mosaic Imagen 3`、`Mosaic Video 2.0`、`Mosaic TTS Pro`、余额数字、Provider 暗示和营销 badge 均不是产品事实，不得照抄。

## 3. 首批模型目录

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

前端不显示 Provider、Provider model ID、deployment、revision、量化、精度、license、snapshot date、参数规模 badge 或“满血版”。三个 Qwen3-TTS 名称中的 `1.7B` 是批准的产品名组成部分。

所有 Demo 模型的 `availability` 为 `demo`，不能伪装成已通过真实 Provider 验收的 `available`。

## 4. 模型广场视觉规格

### 4.1 桌面

- 保留 240px 全局导航。
- TopBar 桌面高度 80px，移动高度 64px。
- 内容最大宽度 1280px，桌面 gutter 24px。
- 页面标题使用 display 56/64，副标题使用 16/24。
- 分类 tabs 与搜索/筛选同一视觉行；tabs 左对齐，搜索区右对齐。
- tabs 使用 16/24，active 使用 accent 和 2px underline。
- 搜索框约 304×44px；筛选按钮 44×44px。
- 主卡片网格使用 `1.1fr 1fr`，列间距 24px。
- 不把卡片统一成相同高度。文本、图片、视频、音频卡片具有不同内容构图。
- 卡片使用 surface、1px line、12px radius，无普通阴影，padding 20px。
- 模型名使用 h3 22/28；描述和能力使用 14/20。
- 书签视觉可以小于 44px，但点击区域必须不小于 44×44px。
- 主动作高度不小于 44px，8px radius。
- hover 只使用边框强调或 1px 位移，不统一缩放。

### 4.2 卡片类型

- 文本卡：左侧信息，右侧折纸式抽象媒体；Qwen 3.5 使用项目资产 `qwen-3-5-folded-paper.png`。
- 图片卡：显示三张 1:1 生成样例；使用 `qwen-image-alpine.png`、`qwen-image-chair.png`、`qwen-image-studio-illustration.png`。
- 视频卡：右侧或下方使用 `hunyuan-video-coastal-car.png`，显示静态播放按钮，但不声称视频已真实生成。
- 音频卡：使用由 HTML/CSS 绘制的静态 waveform、播放按钮和 Demo 时长，不使用图片模拟真实播放器状态。
- 其余模型使用紧凑但仍具差异的两列卡片，不新增第三种视觉系统。

### 4.3 移动

- 目标视口 390×844 和 426×923。
- 默认不显示桌面侧栏；顶部显示 MOSAIC、内部演示和账户入口。
- 内容 gutter 16px。
- 标题 40/48，最多两行。
- tabs 横向滚动、不换行。
- 搜索占剩余宽度，筛选按钮固定 44px。
- 卡片单列，间距 16px，padding 16px。
- 底部固定三项导航：模型广场、生成记录、用量中心，包含 safe-area padding。
- 底部导航不得覆盖卡片、抽屉或聊天 composer。

## 5. 文本对话视觉规格

### 5.1 桌面

- 三段结构：240px 全局导航、320–336px 会话列、自适应主对话区。
- 会话列顶部包含新建会话和设置按钮；会话项 active 使用 accent 10% 混合色。
- 主区 TopBar 高 80px，显示 Qwen 3.5 等稳定产品名和内部演示状态。
- 消息区最大可读宽度约 960px，左右 padding 40px。
- 消息不使用大面积彩色气泡；使用头像、发送者、时间、正文和分隔线的编辑式结构。
- 头像 40×40px；正文 16/28；消息操作 14/20。
- composer 约 104px 高、8px radius、1px line，固定或 sticky 于聊天区底部。
- 消息区独立滚动，composer 不随消息离开视口。

### 5.2 移动

- 会话列转换为顶部会话切换入口或抽屉。
- 消息区单列，头像和正文保持清楚层级。
- composer 全宽并包含 safe-area padding。
- 移动底部全局导航在聊天路由可隐藏，避免与 composer 竞争；必须提供明确返回模型广场入口。

## 6. 公共契约

现有 `PublicProductModel` 保持内部字段隔离。新增：

```ts
export type CatalogCollection = "featured" | "popular" | "new";

export interface ModelCatalogItem {
  model: PublicProductModel;
  collections: CatalogCollection[];
  media: ModelCardMedia;
  favorite: boolean;
}

export interface ConversationMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "complete" | "stopped" | "failed";
  created_at: string;
  request_id?: string;
}

export interface ConversationSummary {
  conversation_id: string;
  product_model_id: string;
  title: string;
  preview: string;
  updated_at: string;
}

export interface Conversation {
  conversation_id: string;
  product_model_id: string;
  title: string;
  messages: ConversationMessage[];
  updated_at: string;
  active_request_id: string | null;
}
```

流事件使用判别联合：`started`、`delta`、`completed`、`stopped`、`failed`。每个事件包含 `request_id`、`conversation_id`、`message_id` 和单调 `sequence`。`started.sequence` 固定为 0；一个请求只能有一个终态；终态后不得追加 delta。

## 7. Service 边界

`ServiceRegistry` 增加：

- `ModelCatalogService`
- `ConversationService`

模型目录支持 list、get、toggleFavorite。对话支持 list/get/create/send/regenerate/stop。

页面、feature 和 shared UI 不得直接调用 `fetch`、读取 DemoScenario、读取 DemoStateStore 或 import 具体 Demo/API Adapter。Service composition root 是唯一实现选择点。

## 8. DemoScenario 与状态 v2

DemoScenario 固定：

- seed `8202026`
- 12 个模型
- 至少两个 Qwen 3.5 会话
- 两轮上下文脚本
- 超时、内容拒绝、停止脚本
- 固定流式 chunk 边界

DemoState 升级为 schema v2，保存：

- 认证状态
- favorites
- selected model
- conversations
- chat requests 和 stream cursor
- unsent drafts
- updatedAt

必须支持 v1 → v2 迁移，只迁移认证字段，其余从 DemoScenario hydrate。损坏、未知或未来版本 fail-closed 到稳定初始场景。localStorage 不可用时继续使用浏览器会话级内存 fallback。

所有状态变更通过 `DemoStateStore.update()`，避免流事件使用过期快照覆盖其他写入。

## 9. 幂等与流式语义

- `clientRequestId` 作用域为 conversation + operation。
- 同 key 同 payload 返回原 request，不追加消息。
- 同 key 不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- 同一会话已有 active request 时返回 `CONVERSATION_BUSY`。
- stop 保留已产生的 assistant 文本并写入 `stopped`。
- 订阅 Abort、页面卸载或刷新只中止当前订阅，不把业务请求写成 failed。
- regenerate 使用新 key，只替换最新 assistant 候选，不重复用户消息。
- 刷新后从 `nextChunkIndex` 和已保存文本恢复，不重复 delta。

## 10. 错误语义

- `MODEL_CATALOG_UNAVAILABLE`
- `MODEL_NOT_FOUND`
- `CONVERSATION_NOT_FOUND`
- `MESSAGE_EMPTY`
- `CONVERSATION_BUSY`
- `IDEMPOTENCY_KEY_REUSED`
- `PROVIDER_TIMEOUT`
- `CONTENT_REJECTED`
- `STREAM_RESPONSE_INVALID`

错误使用现有 typed service error，保留 request ID，不显示 Provider 原始错误、URL 或内部部署信息。

## 11. 状态与交互

模型广场：Loading、Empty search、Partial availability、Error、Offline。

聊天：Loading、Empty conversation、Streaming、Stopped、Completed、Failed、Timeout、Content rejected、Offline draft。

状态必须同时使用文字和结构，不只依赖颜色。余额不足不进入 Phase 2，因为本阶段没有 UsageService；标记为 Phase 3 N/A，不能静态伪造。

## 12. 自动化与视觉 Gate

- 契约与内部字段拒绝。
- 精确 12 个模型，分类数量 6/2/1/3。
- 分类与搜索交集、收藏幂等和刷新持久化。
- 文本模型进入聊天；媒体模型进入诚实的后续工作台路由。
- 两轮上下文、确定性 stream、stop、regenerate、刷新恢复。
- axe serious/critical 为 0。
- 1440×900、1728×1117、390×844、426×923 无横向溢出。
- 几何断言与截图共同验收，不允许只依赖快照。
- 正常 Gate 不允许 `--update-snapshots`。

## 13. 明确排除

- 真实模型和 Provider 调用。
- 服务端认证和受保护数据。
- 真实余额、预留、账本和扣费。
- 图片、视频、音频任务提交与结果。
- 对象存储和上传。
- PostgreSQL 中的模型/会话持久化。
- Ollama 公网测试。

媒体模型可以展示并进入对应路由，但工作台继续显示诚实的后续阶段说明，不生成虚假结果。
