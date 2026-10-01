# 状态与恢复

每本书只有一个 `learning/progress.json`。它是游标、课节状态、mastery、coverage、复习计划、reading scope 和审计状态的唯一事实源；Markdown 与 `.cache` 都不能反向覆盖状态。

任何状态操作先按 `assets/progress.schema.json` 校验，再执行跨字段语义校验。写入必须通过 `scripts/progress.py`：校验旧状态、修改内存副本、写同目录临时文件、刷盘、再次校验、原子替换。缺少真实 `jsonschema`、版本不兼容、旧状态损坏、新状态无效或原子替换失败时均 fail closed。

## 持久化规则

- `phase` 是下一动作的唯一持久化事实源。
- 不保存 `next_action`。
- `last_completed_action` 只存在于各自 cursor 内，不参与决策。
- 根 `updated_at` 可以记录普通写入，但永远不参与“继续”排序。
- invocation 可以记录 `last_invocation`，但不得改变学习与阅读状态。
- `reading_scope` 必须把每个已识别 chapter 恰好归入 included 或 excluded；排除必须有非空原因。
- chapter 只持久化 `browse_status`（unseen / skimmed / mapped）与 `deep_read_status`；覆盖百分比由 source block 数量派生，不持久化重复的通用 coverage 状态。
- `reading_lens` 保存一个 primary 和去重的 supporting lens；primary 不得在 supporting 中重复。

恢复不依赖聊天历史。先验证磁盘状态与 cursor 的 chapter/lesson 引用，再按 `references/modes-and-routing.md` 选择 cursor，从其准确 `phase` 重建下一动作。损坏状态只作为恢复证据保留，不得悄悄生成第二事实源。
