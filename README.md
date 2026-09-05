# anime-voice-sorter

把一部动画拆成**按人分好组的纯净人声片段**，用于音色收集。

```
输入：  动画的若干集（视频或音轨）+ 字幕（可选）
       可选：少量标注（每人几条样本）

输出：  out/
        ├─ speaker_01/  *.wav        原始采样率、无 BGM、单人、无重叠
        ├─ speaker_02/  *.wav
        ├─ _misc/                    时长不足以单独成组的零散说话人
        ├─ _rejected/                被质量闸门拒收的片段（保留以便复查）
        └─ manifest.parquet          每个片段的完整元数据与判决理由
```

这是一个**聚类**工具，不是分类工具：说话人数量与身份都未知，使用者事后才命名分组，甚至可以不命名。

## 状态

**M1（工程骨架）完成，管线尚未实现。** 详细进度、下一个动作与阻塞项见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 环境

需要 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run avs doctor
```

`doctor` 会报告 CUDA 可用性与各关键依赖的加载情况。开发机配置为 Windows + CUDA 12.8 轮子，CI（Linux）自动改用 CPU 轮子。

diarization 用的 `pyannote/speaker-diarization-community-1` 是 gated 模型，首次使用前需在 HuggingFace 上接受条款并配置 token。

## 文档

从 [`docs/README.md`](docs/README.md) 进，那里有索引和各文档的职责划分。

- [`docs/DESIGN.md`](docs/DESIGN.md)：管线结构、数据模型、失败模式、评估方法
- [`docs/TOOLING.md`](docs/TOOLING.md)：选型的唯一事实来源，以及现成工具调研
- [`docs/ROADMAP.md`](docs/ROADMAP.md)：进度的唯一事实来源
- [`docs/DECISIONS.md`](docs/DECISIONS.md)：决策记录，「为什么不那样做」
- [`docs/PRIOR_ART_AUDIT.md`](docs/PRIOR_ART_AUDIT.md)：前身项目的问题清单，已冻结

## 一条贯穿全流程的红线

16 kHz 只用于分析，成品永远从原始采样率音轨按时间戳切。音色模型多在 40 到 48 kHz 训练，搞错会让成品**静默报废**：听感上不明显，流程里也不报错。

## 许可

TBD
