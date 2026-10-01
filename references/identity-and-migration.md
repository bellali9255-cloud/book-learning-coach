# 稳定身份与来源迁移

book、chapter、lesson、source block、review card、method、scene 和 mapping 都使用随机稳定 ID；顺序、标题、页码和行号只是展示元数据。禁止 `src-ch03-p014` 这类把顺序编码进身份的 ID。

重新转换时按以下证据迁移：内容指纹、邻接关系、所属章节、规范化标题与局部上下文。行号只能辅助人工核对。重复标题或相似段落不能单独证明身份。

## 双哈希决策

- original hash 改变：视为版本或正文变化，暂停自动推进并生成迁移报告。
- original 不变而 canonical 改变：视为转换结果变化，在 `.cache` 生成候选并重新迁移锚点、审计回链。
- 两者均不变：可按原状态继续。

只有可靠匹配才沿用原 ID 和学习记录。无法可靠判断的 chapter、lesson 或 source block 必须进入 `needs_review`，不得为了保持进度而强行迁移。候选通过前不替换 canonical source。

所有 Markdown 内容资产由 `scripts/asset_store.py` 根据稳定 ID upsert；恢复或重试不得追加重复实体。
