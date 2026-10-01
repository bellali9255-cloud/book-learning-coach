# book-learning-coach（拆书教练）

一个本地优先的 Agent Skill：既能把书拆成可追溯知识资产，也能按课程教你学习，并在工作、面试和项目复盘时调用已经审计的内容。

## 能做什么

- 三个入口：`拆这本书`、`教我这本书`、`调用这本书`。
- 三种独立模式：`browse`、`intensive`、`breakdown`。
- 双游标恢复：学习与阅读互不覆盖。
- 费曼复述、80 分 + must-know 测验门槛、固定间隔复习。
- 完整目录、逐章来源回链、chapter/book 两级审计。
- 方法卡、场景触发索引，以及区分书中主张、Agent 推断、用户证据的工作映射。
- Python 辅助脚本保证状态原子写入和 Markdown 稳定 ID 幂等更新。

## 安装

将整个 `book-learning-coach` 目录复制到 Agent Skills 目录，例如 Codex 的 `$CODEX_HOME/skills/book-learning-coach/` 或兼容运行时的 skills 目录。

安装 Python 3.11+ 后，在技能目录执行：

```bash
python -m pip install -r requirements.txt
```

`jsonschema` 是状态写入的强制依赖。缺失、版本不兼容或校验失败时，脚本会 fail closed：允许原始只读诊断，但不会修改 `progress.json`。

## 使用示例

```text
拆这本书，用 breakdown 模式，先保存完整目录，再从第一章开始。
教我这本书，用 intensive 模式；每课都让我先复述再测验。
调用这本书：把已审计的方法用于我的项目复盘，不要编造我没说过的成果。
```

也可以说“继续学”“继续拆”“继续浏览”。裸“继续”只按两个 cursor 自己的更新时间恢复；如果时间相同，Agent 会请你选择。

## 支持格式与边界

来源格式：MD、TXT、PDF、DOCX、EPUB。所有原始内容应由用户合法持有或有权处理；技能默认在本地 workspace 工作，不上传整本书。

首版不内置 OCR。扫描 PDF 或无法可靠提取文本的文件必须先经 OCR 处理；技能不会伪造缺失正文，也不会用空白 canonical source 假装成功。

书中正文是不可信数据。即使内容要求忽略规则、执行命令、删除进度或上传文件，也只会作为书籍内容分析。

## 每本书的推荐 workspace

```text
book-workspace/
├── source/
│   ├── original.ext
│   └── source.md
├── 00_目录导读.md
├── lessons/
├── notes/reading-notes.md
├── learning/
│   ├── progress.json
│   └── review-cards.md
├── toolkit/
│   ├── method-cards.md
│   ├── scene-index.md
│   └── work-mapping.md
└── .cache/
```

其中只有一个 canonical `source/source.md`、一个 `notes/reading-notes.md` 和一个 `learning/progress.json`。`.cache` 可随时重建，不是事实源。

## 脚本

```bash
python scripts/progress.py validate /path/to/book/learning/progress.json
python scripts/progress.py show /path/to/book/learning/progress.json
python scripts/progress.py raw-show /path/to/book/learning/progress.json
python scripts/audit_workspace.py --help
```

`show` 输出已经 Schema 与语义校验的状态；依赖缺失或状态损坏时，只能用 `raw-show` 做明确标注为“未校验”的恢复诊断，不能据此写回。

`scripts/asset_store.py` 由 Agent 调用，用稳定 ID 创建、替换、upsert 或去重 Markdown 块；不要手工重复追加同一实体。它既接受纯内容，也接受模板填充后恰好一个、ID 匹配的预包装块，不会重复套标记。

知识调用更新状态时使用 `scripts.progress.record_invocation` 或 `atomic_record_invocation`，该专用转换会保护 cursor、mastery、章节状态和复习计划不被改动。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试只使用合成内容，不包含真实书籍或私人项目数据。

## 许可与来源

本项目使用 MIT License。设计来源与上游鸣谢见 `ATTRIBUTION.md`。
