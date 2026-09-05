# 路线图与当前状态

> 最后更新：2026-09-05
> 本文档是**进度的唯一事实来源**。设计见 `DESIGN.md`，选型见 `TOOLING.md`，决策理由见 `DECISIONS.md`。

## 当前状态

**M1 完成，M2 未开始，被 HuggingFace token 部分阻塞。**

环境已验证可用（`uv run avs doctor`）：

```
torch           2.11.0+cu128
cuda available  True
device          NVIDIA GeForce RTX 4060 Laptop GPU  (compute 8.9)
torchaudio      ok
pyannote.audio  ok   4.0.7
audio_separator ok   0.47.0
pysubs2         ok
soundfile       ok
```

`ruff check` / `ruff format --check` / `mypy src`（strict）/ `pytest` 四项全绿。

## 下一个动作

**在写任何管线代码之前，先手动跑一次可行性验证，回答一个问题：diarization 在动画音轨上到底能做到什么水平。**

这个数字决定 M2 到 M5 的投入分配，所以它必须排在工程实现之前：

- cluster 纯度已经不错 → 重心放跨集链接与导出，review 做轻量
- 纯度差 → 先查前处理（分离质量、片段长度、采样率），review 要做重

验证分两半，可并行：

| 半 | 内容 | 是否阻塞 |
| --- | --- | --- |
| A | `audio-separator` + Mel-Band Roformer 分离一集，测效果与耗时 | 否，可立即做 |
| B | `pyannote community-1` diarize 分离后的人声，听几个 cluster 估纯度 | **是**，见下 |

## 阻塞项

| 项 | 阻塞什么 | 解除方式 |
| --- | --- | --- |
| **HuggingFace token** | 验证的 B 半、以及后续所有 diarization 工作 | 需在 `huggingface.co/pyannote/speaker-diarization-community-1` 接受条款并生成 token。这是账号操作，必须由使用者本人完成 |

## 里程碑

| 里程碑 | 内容 | 验收 | 估时 | 状态 |
| --- | --- | --- | --- | --- |
| **M0** | 新建仓库、`.gitignore`、ASCII 化、文档迁移 | clone 干净 | 0.5 天 | **完成** |
| **M1** | 工程骨架：uv、`src/avs` 包、CLI、config、ruff/mypy/pytest/CI | `avs --help` 可用，四项检查全绿 | 1 天 | **完成** |
| **M2** | 纵向打通：ingest → separate → diarize → embed → cluster → export，单集，不做 review 与质量闸门 | 一集动画产出按人分组的目录，人工听着大致对 | 0.5 天（因大量复用现成组件，从原估的 1.5 天下调） | 未开始 |
| **M3** | 跨集说话人链接、聚类阈值标定、长尾归并 | 全系列产出稳定分组，B-cubed F1 有数字 | 1 天 | 未开始 |
| **M4** | review 界面：命名 / 合并 / 拆分 / 阈值滑块 | 修正一部动画的分组耗时 < 15 分钟 | 0.5 到 1.5 天，取决于 voxmap-studio 是否可用 | 未开始 |
| **M5** | 质量闸门、双轨导出、manifest 完整化 | 成品无重叠、无 BGM 残留、原始采样率 | 1 天 | 未开始 |
| **M6** | few-shot 通道、评估脚本、README、打包 | 他人可装可用 | 1 天 | 未开始 |

M2 的估时下调，是因为 `TOOLING.md` 的调研确认了分离、diarization、嵌入三个环节都有可直接用的组件，省下的时间应投到 M3，那是唯一没有现成方案、也是本工具真正创造价值的部分。

## 开放问题

| 问题 | 影响 | 何时需要答案 |
| --- | --- | --- |
| 这个工具只给自己用，还是要能分发给别人装？ | 决定 M6 的投入（打包、错误提示、模型自动下载、文档语言） | M6 之前 |
| `voxmap-studio` 的仓库地址是什么？论文里没给 | 决定 M4 是复用现成工具还是自己写 Gradio，差 1 天 | M4 之前 |
| 是否需要跨作品的说话人库（同一声优在不同作品间关联）？ | 另一个量级的问题 | 建议明确排除在 v1 外，暂不需要答案 |
| 评估用的标注从哪来？ | 影响 M3 能否给出 B-cubed F1 | M3 之前。前身仓库现有的 95 + 215 条标注可先当迷你评估集 |

## 已完成事项的细节

### M1 中值得记住的坑

- **`audio-separator` 有未声明的依赖**：import 时需要 `audioread` 但没写进自己的 dependencies，装完直接 `ModuleNotFoundError`。已显式加入本项目依赖。
- **torch 必须按平台绑定 index**（见 ADR-011）：首次 lock 时解析出了 torch 2.14 配 torchaudio 2.11 的不兼容组合，已把两者都钉在 2.11。
- **ruff 的 RUF001/002/003 对中文是纯误报**，已关闭；`docs/` 已排除出 format 范围，否则它会去改文档里的示例代码块。
