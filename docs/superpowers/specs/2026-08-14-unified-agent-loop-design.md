# 统一 Agent 循环 + Token 上下文

日期:2026-08-14
状态:已批准

## 背景与目标

现状有两条路:IntentClassifier 把用户输入分为 CHAT(纯聊天,无工具)与 TASK(AgentEngine
多步工具循环)。分类不稳定(日志显示同一句"查电脑状态"两次 TASK 一次 CHAT),判成 CHAT
时模型完全没有工具能力;AgentEngine 的事件接线也出过丢事件、后台线程弹窗崩溃等问题。

目标:
1. 合并为**一条路**:每个消息都走统一的带工具流式循环,由模型自己决定是否调用工具。
2. 上下文管理从"固定 20 条消息"改为 **token 预算**(默认 64K),状态栏实时显示用量。

## 架构

```
用户消息
  ↓
构造上下文:系统提示(人设+记忆+工具使用准则) + token 裁剪后的历史 + 用户消息
  ↓
循环(最多 12 轮):
  流式调用 provider.chat(tools=全部工具清单, thinking=...)
    ├─ 文本增量 → UI(气泡流式)
    ├─ 思考增量 → UI(灰色思考条)
    ├─ 工具调用增量 → UI(🔧 块流式)
  ├─ 无 tool_calls → 存回复、更新记忆、结束
  └─ 有 tool_calls → 高风险弹确认框(主线程 ConfirmBridge)→ 执行 → 记录步骤
                     → tool 结果回喂模型 → 继续循环
连续失败 ≥3 或超轮数 → 如实汇报失败并结束
```

## 组件变化

| 文件 | 动作 |
|---|---|
| `core/tokens.py` | 新增:token 估算(中文 1 字≈1 token,其余 4 字符≈1 token) |
| `core/events.py` | 新增:AgentEvent(从 engine 迁来) |
| `core/chat.py` | ChatService 吸收工具循环:新增 tools/policy/confirm/stop/recorder/context_limit 注入;`stream_reply` 增加 `on_event`;`_build_messages` 按 token 预算裁剪历史 |
| `agent/engine.py` | 删除(逻辑并入 ChatService) |
| `core/tasks.py` | 删除(TaskRouter 退役) |
| `core/intent.py` | 删除(不再分类) |
| `storage/config.py` | 新增 `context_limit_tokens: int = 65536` |
| `ui/settings_dialog.py` | 「模型」tab 加上下文上限输入(K tokens) |
| `ui/main_window.py` | `_send` 直接调 `chat.stream_reply`,不再走 router;状态栏显示 `上下文 X.XK/64K` |
| `main.py` | 组装精简:ChatService 注入 tools/policy/confirm/stop/recorder |

保留:确认弹窗(ConfirmBridge)、停止按钮、TaskRecorder 步骤记录、自动驾驶开关、
记忆系统、人设、事件类型(text/reasoning/tool_start/tool_args/step_start/step_end/done/failed)。

系统提示追加工具使用准则:只在用户要求时动手、如实报告、禁止破坏性操作、
失败换方式重试。

工具中间过程不进会话历史(只存用户消息与最终回复,与现状一致)。

## Token 预算

- 默认上限 64K(deepseek-chat 支持,设置可调)。
- 构建请求时:系统提示 + 工具清单 JSON + 预留输出 4096 token 计入预算;
  历史消息从最新往前装,超限丢最旧的;历史条数硬上限 200 防退化。

## 错误处理

- 模型请求异常:worker 捕获 → chat.error → 弹窗 + 日志(现有)。
- 工具执行失败:tool 结果如实回喂模型;连续 3 次失败中止。
- 用户拒绝确认:记录"用户拒绝了此操作",继续循环。
- 未捕获异常:excepthook 写 assistant.log(已实现)。

## 测试

- `test_tokens.py`:中英混排估算、边界(空串/纯中文)。
- `test_chat.py` 重写:无工具→普通流式回复;工具调用→执行+回喂+多步直至完成;
  确认拒绝;连续失败中止;步数上限;token 裁剪(旧消息被丢弃);工具消息不入历史。
- 删除 `test_agent_engine.py` / `test_tasks.py` / `test_intent.py`。
- `test_ui_smoke.py`:ChatService 新签名适配;状态栏 token 文案断言。
- 全量测试保持绿,离屏渲染验证聊天视图不受影响。

## 风险

- 每轮请求带工具清单,多耗数百 token(可接受,换来统一能力)。
- 闲聊时模型可能误调低风险工具(网页搜索等):靠系统提示约束,后续可加工具使用统计观察。
