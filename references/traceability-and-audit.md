# 可追溯性与两级审计

每条正式笔记至少保存 `source_block_id`、`chapter_id` 和便于人工定位的显示信息。有效回链必须解析到唯一 canonical `source/source.md`；`.cache` 中的锚点不构成回链证据。

先运行 `scripts/audit_workspace.py`。硬错误包括：canonical source / reading notes / progress 不唯一、原始文件或双哈希不匹配、任一受管 Markdown 标记损坏、稳定 ID 重复、source ref 缺失、状态无效、范围未分类或排除原因缺失。软警告不会自动授权正式资产。

## Chapter-level audit

一个 included chapter 只有在 `deep_read_status` 与 `audit.chapters[id].status` 均为 `audited`，canonical reading notes 存在该章稳定 ID 块并覆盖其来源块、所有回链有效且无 issue 时才通过。通过后可生成 chapter-scoped 方法卡、场景索引和工作映射：

```yaml
scope: chapter
chapter_id: ch_xxxxxxxx
audit_ref: learning/progress.json#audit.chapters.ch_xxxxxxxx
```

可选快照只能命名为 `book_audit_status_at_generation`，不能充当当前状态。

## Book-level audit

只有 `reading_scope.included_chapter_ids` 全部完成章节审计、所有章节已分类、跨章一致性与回链检查通过，并且 `audit.book_status = audited`，才授权 book-scoped 或 cross-chapter 正式资产。章节审计通过不代表整本书通过。
