# 入口、模式与恢复路由

三个入口与三个模式是两条独立维度，不建立优先级。

| 用户入口 | 默认目标 |
|---|---|
| 拆这本书 | 建立结构、逐章可追溯笔记、审计与知识资产 |
| 教我这本书 | 课程化讲解、费曼复述、测验、补救与复习 |
| 调用这本书 | 用已经审计的知识回答真实问题 |

模式只有 `browse`、`intensive`、`breakdown`。用户明确指定时采用其选择；未指定时根据目标推荐，但不得用“精学优先”等隐藏优先级覆盖用户意图。

## “继续”路由

先运行 `scripts/progress.py` 的状态校验，再使用 `select_resume_cursor`：

- “继续学”只选 `learning_cursor`。
- “继续拆”只选 mode 为 `breakdown` 的 `reading_cursor`。
- “继续浏览”只选 mode 为 `browse` 的 `reading_cursor`。
- 裸“继续”只比较 phase 尚未 `complete` 的 cursor 自己的 `updated_at`；相同、无候选或时间不可比较时请求用户选择。

恢复后从 cursor 保存的准确 `phase` 继续，不从章节号、lesson 号、根 `updated_at`、`last_invocation.at` 或聊天历史猜测。`last_completed_action` 只用于展示恢复摘要。

调用流程不是 cursor。调用不得改变 cursor、mastery、coverage、lesson status 或 review schedule。
