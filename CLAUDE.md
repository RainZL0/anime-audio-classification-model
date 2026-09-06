# anime-voice-sorter

主线是字幕切段后的说话人分类；语气词和噪声暂时搁置。不要重新引入质量配额作为分类前置条件。

先读 README、docs/STATUS.md、docs/HISTORY.md。流程和指标见 docs/HOW_IT_WORKS.md；已完成实验见 docs/EXPERIMENTS.md。当前计划只维护在 STATUS，实验细节集中在 EXPERIMENTS，长期教训提炼到 HISTORY，不追加失效决策流水账。

嵌入诊断已完成：近邻检索几乎全对，51 对漏合全部含短于 1.5 秒的片段。single/complete/mutual_knn 都不超过 average；整句字幕重切短片段的闸门核对未通过，已停。针对短片段的 two_stage 是唯一有改善的候选（runs/groups/uma-two-stage.json，旧标签上 86/0/32 对 67/0/51），但分界与阈值都用了旧标签，尚未替换默认分组。两集分别标注，跨集同一角色必须同名（红毛 已统一为 Nice Nature；ep02 的 解说/解说2 是两个人，已改名为 解说A/解说B）。当前下一步是两集全量重标（avs label --all，485 条，存 annotations/ep01-full.json 与 ep02-full.json），只用新标签验证错合与漏合；不要把“换嵌入模型”“重切短片段”或“继续试参考阈值”当作当前计划。旧的 62 条抽样标签（ep01_v4/ep02）已按标注者要求删除，只留下 annotations/names.json 里的 27 个角色名；EXPERIMENTS 里基于旧标签的数字是历史记录，无法重算。抽样补标那条路（avs label-plan）已被全量重标取代。新标签验证尚未实施。

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
