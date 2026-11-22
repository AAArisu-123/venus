# 架构说明

这个项目的结构不复杂：核心聊天只用标准库，数据放在本机 SQLite，模型走任意 OpenAI 兼容的 `/chat/completions` 接口。QQ 和心情状态是可选扩展，不装也能用。

## 总览

```text
                         ┌──────────────────────────────┐
  命令行 / QQ 私聊 ────▶ │ 入口层                        │
                         │ __main__.py / qq_bot.py       │
                         │ qq_handler.py / commands.py   │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │ 安全与提示词层                │
                         │ privacy.py / safety.py        │
                         │ prompt.py / language.py       │
                         └──────────────┬───────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
      ┌───────────────┐        ┌────────────────┐        ┌────────────────┐
      │ 记忆与画像     │        │ 模型客户端      │        │ 主动消息        │
      │ memory.py     │        │ __main__.py    │        │ proactive*.py  │
      │ long_memory.py│        │ web_tool.py    │        │ activity.py    │
      │ memory_recall │        │ affect*.py     │        │ presence.py    │
      │ profile.py    │        └────────────────┘        └────────────────┘
      └───────┬───────┘
              ▼
      ┌───────────────┐
      │ 本地 SQLite    │  data/venus.sqlite3（明文，需自行保护）
      └───────────────┘
```

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `venus/__main__.py` | 命令行入口、模型请求、一次对话的完整流程 |
| `venus/config.py` | 环境变量与本地路径配置；不依赖 QQ 可选包 |
| `venus/prompt.py` | 分层拼装系统提示词：安全层 → 人设 → 画像 → 记忆 → 示例 → 历史 → 本轮提示 |
| `venus/safety.py` | 所有人设共享的最低边界 |
| `venus/language.py` | 共用的语气、长度、颜文字和主动起话题规则 |
| `venus/privacy.py` | 发送前拦截高置信度密钥与个人信息 |
| `venus/persona.py` | 读取并校验人设 JSON |
| `venus/memory.py` | 每个 `(persona, user)` 的短期对话历史 |
| `venus/long_memory.py` | 长期记忆的增删改查与字段迁移 |
| `venus/memory_recall.py` | 关键词相关性 + 重要性 + 新近度的召回排序 |
| `venus/auto_memory.py` | 从明确的第一人称偏好句自动提取记忆（带开关与同意记录） |
| `venus/profile.py` | 用户显式设置的称呼、风格、边界 |
| `venus/commands.py` | QQ 私聊中的斜杠命令 |
| `venus/activity.py` | 每个用户的活跃度与静默时长 |
| `venus/proactive.py` | 主动消息的时段、随机目标与幂等认领 |
| `venus/proactive_runner.py` | 周期性执行主动消息发送 |
| `venus/proactive_composer.py` | 生成主动开场白 / 生活小事 |
| `venus/presence.py` | 最后发言时间与未回复计数（追话能力，默认未接线） |
| `venus/life.py` | 角色“今天在做什么”的本地小记录 |
| `venus/affect.py` / `affect_appraisal.py` | 可选 AnimaFlux 心情状态 |
| `venus/web_tool.py` / `web_settings.py` | 可选的 DeepSeek 联网搜索 |
| `venus/qq_bot.py` / `qq_handler.py` / `qq_events.py` | QQ 官方机器人接入 |
| `venus/qq_access.py` / `pairing.py` / `pair_cli.py` | 白名单与本地配对审批 |
| `venus/doctor.py` | 配置、模型、QQ 和数据路径自检 |
| `venus/qq_service.py` | Windows 计划任务入口，只写固定状态日志 |

## 一次普通对话

1. 入口读取消息，命令层先判断是否为 `/` 命令。
2. `privacy.detect` 检查密钥、证件号、银行卡号、手机号、邮箱等；命中时直接返回安全提示，不读历史、不调用模型、不落库。
3. 读取该 `(persona, user)` 的历史、画像、相关长期记忆和生活小事。
4. 可选：读取或评估 AnimaFlux 心情。
5. `prompt.build_messages` 组装分层提示词。
6. 调用 OpenAI 兼容接口；如开启联网，则改走 DeepSeek 搜索接口并附带来源。
7. 成功后保存用户与助手两条消息，更新记忆使用计数和心情状态。

## 主动消息

- 每个用户首次正常聊天后自动建立 `mode = random` 计划，默认开启。
- 生产策略只保留一个晚间窗口 `19:00–21:00`，每天最多 1 条。
- 发送前要求最近 6 小时没有用户消息，且不超过 7 天完全沉默。
- 每个时段先用 `proactive_slot_claim` 原子认领，再生成和发送；因此崩溃或发送失败不会重复。
- `/主动 关闭` 写入持久关闭状态，默认计划不会把它重新打开。

## 本地数据表

| 表 | 内容 |
| --- | --- |
| `messages` | 每个角色与用户的聊天历史 |
| `memories` | 长期记忆（分类、重要性、来源、使用次数） |
| `user_profile` | 显式画像 |
| `auto_consent` | 自动记忆开关 |
| `life_log` | 角色生活小事 |
| `affect_state` | 可选心情状态 |
| `activity` | 活跃事件（去重） |
| `proactive_schedule` | 主动消息计划 |
| `proactive_slot_target` / `proactive_slot_claim` | 当日随机分钟与幂等认领 |
| `proactive_random_target` / `proactive_claim` | 旧版随机路径的兼容表 |
| `web_settings` | 联网开关 |
| `presence` | 最后发言时间与追话计数 |

QQ 配对使用独立的 `data/pairing.sqlite3`。

## 几个取舍

数据都留在本机，没有账号系统；未配置或未授权时直接拒绝，不猜着放行。主动消息先写认领再发送，所以重试不会刷屏。模型返回的内容只当文本或数值用，不执行里面的指令。QQ 和 AnimaFlux 都是可选的，缺了也不影响普通聊天。

## 扩展点

- 新增人设：在 `personas/` 放一个 JSON，用 `--persona` 指定。
- 新增命令：在 `commands.py` 注册处理函数。
- 新增记忆来源：写入 `memories` 表并复用 `memory_recall.recall`。
- 新增 IM 平台：参考 `qq_handler.py`，实现“收消息 → `answer` → 发消息”的适配层。
