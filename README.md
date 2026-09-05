# anime-voice-sorter

按字幕切出动画对白，再把同一角色的声音归到一起。**先完成说话人分类，偶发语气词和噪声后置。** 不按音质排名丢掉一半，也不把短小组混到一个人物桶里。

流程已跑通，身份分组仍需改善。当前进度、假设和下一步统一见 [项目现状](docs/STATUS.md)；本页只维护使用方法。

## 使用

安装后用 `uv run avs --help` 查看命令。需要 FFmpeg；GPU 环境、字幕对齐与模型说明见 [工具](docs/TOOLS.md)。

```powershell
uv sync --locked
uv run avs doctor
# 新的一集；省略 --offset 时自动估计字幕偏移
uv run avs prepare data/raw/uma_s2_03.flac --subs "对应字幕.ass" --name ep03 --out runs/episodes/ep03
uv run avs embed runs/episodes/ep03
```

本机第 1、2 集已迁移好，可直接分组，不必重算模型：

```powershell
uv run avs group runs/episodes/ep01 runs/episodes/ep02 --out runs/groups/uma-next.json --threshold 0.5
uv run avs evaluate runs/groups/uma-next.json --annotation annotations/ep01_v4.json --annotation annotations/ep02.json --out runs/groups/uma-next-evaluation.json
uv run avs export runs/groups/uma-next.json --out out/uma-next
```

重新调分组只需再跑 `group`；`--method` 可选 average（默认）、single、complete、mutual_knn、two_stage。前三种已实测都不超过 average；two_stage 先分长片段再挂短片段，是旧标签上唯一有改善的候选，等待新标签验证后才会成为默认。分组文件与导出目录用新名字，避免旧音频残留混进新结果。

固定片段比较两个模型（阈值 0.20—0.90，步长 0.01，保留错合与漏合完整曲线）：

```powershell
uv run avs embed runs/episodes/ep01 runs/episodes/ep02 --model wespeaker-resnet293
uv run avs compare runs/episodes/ep01 runs/episodes/ep02 --annotation annotations/ep01_v4.json --annotation annotations/ep02.json --out runs/comparison-next.json
```

比较前会核验两种声纹覆盖同一批片段；使用人工标签挑出的阈值只能算探索结果。`--model` 可只比一个模型，`--method` 可重复给出连接规则，同时比较规则曲线。

身份参考实验（保留原分组；每个目标角色至少有 4 条精确标签）：

```powershell
uv run avs references runs/groups/uma.json --annotation annotations/ep01_v4.json --annotation annotations/ep02.json --role teo --role trainer --role 皇帝 --out runs/references-next
# 增加 --nearest：按最近参考声音归属，扫描四个距离阈值
```

每角色分别取 1/2 条参考，各重复 20 次划分。报告中的基线和参考方法始终用同一批剩余片段评分；参考候选带有已用标签 ID，`evaluate` 会自动排除它们。输出仅为实验候选，当前实测不足以替换默认分组。

嵌入诊断（固定片段，两模型缓存，不重跑音频模型；`--groups` 可选，用来区分组内与组间错误）：

```powershell
uv run avs diagnose runs/episodes/ep01 runs/episodes/ep02 --annotation annotations/ep01_v4.json --annotation annotations/ep02.json --groups runs/groups/uma.json --out runs/diagnosis-next
```

输出报告、全部标签配对的距离，以及 `examples/` 下可试听的错误实例。近邻排除查询自身；只有一条标签的角色不作查询，但留作干扰项；未标注近邻只算线索。

```powershell
uv run avs label runs/episodes/ep03 --archive annotations/ep03.json --count 50
```

`label` 从全量片段随机抽样，按时间顺序展示，对照画面报名字，每条直接存进人工归档。不是让你凭记忆听音分组。

导出回到原始采样率的人声轨；16 kHz 副本只用于分析。短于 1 秒、没有可靠声纹的片段保留在 `_unassigned`，不会被安静丢弃。

[文档导航](docs/README.md) · [人工标注](annotations/README.md)
