# anime-voice-sorter

主线是字幕切段后的说话人分类；语气词和噪声暂时搁置。不要重新引入质量配额作为分类前置条件。

先读 README、docs/STATUS.md、docs/HISTORY.md。流程和指标见 docs/HOW_IT_WORKS.md；已完成实验见 docs/EXPERIMENTS.md。当前计划只维护在 STATUS，实验细节集中在 EXPERIMENTS，长期教训提炼到 HISTORY，不追加失效决策流水账。

嵌入诊断已完成（runs/diagnosis）：近邻检索几乎全对，50 对漏合全部含短于 1.5 秒的片段，且多数跨集。连接规则对照也已完成：single/complete/mutual_knn 都不超过 average。当前下一步是只对短片段做整句字幕重切的针对性对照，标签必须重新精确匹配；不要把“换嵌入模型”“换聚类规则”或“继续试参考阈值”当作当前计划。重切对照尚未实施。

## 工作约束

- 人工真值只有 annotations 中对照画面确认的 name。使用支持样本时从验收标签中排除。
- 片段范围不同就不能继承标签；同模型标签不能验证该模型。
- 先固定片段比较分组，再单独比较切段变化。错合与漏合必须一起报。
- 嵌入近邻诊断排除查询自身；仅一条标签的角色不作同人检索查询，但保留为干扰项。未标注近邻不能算错人，按角色和有效查询覆盖报告，区分事实与假设。
- 音频分析用 16 kHz；导出回到原始采样率人声，不能升采样假装恢复高频。
- 原始素材、人工记录、有效模型和昂贵缓存不属废弃内容。删除先核对引用与迁移。
- 用大白话说明目标、实测、代价与未知，不用漂亮分数替代身份验收。

## 检查

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```
