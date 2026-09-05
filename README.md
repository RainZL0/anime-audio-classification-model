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

早期开发中。当前完成到 M1（工程骨架），管线尚未实现。

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 仓库治理 | 完成 |
| M1 | 工程骨架：uv、包结构、CLI、CI | 完成 |
| M2 | 纵向打通：分离 → diarize → 嵌入 → 聚类 → 导出 | 进行中 |
| M3 | 跨集说话人链接、阈值标定、长尾归并 | |
| M4 | review 界面（命名 / 合并 / 拆分） | |
| M5 | 质量闸门、双轨导出 | |
| M6 | few-shot 通道、评估、打包 | |

## 环境

需要 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run avs doctor
```

`doctor` 会报告 CUDA 可用性与各关键依赖的加载情况。

开发机配置为 Windows + CUDA 12.8 轮子，CI（Linux）自动改用 CPU 轮子，见 `pyproject.toml` 的 `tool.uv.sources`。

## 设计文档

- [`docs/DESIGN.md`](docs/DESIGN.md)：管线设计、数据模型、已知失败模式、评估方法
- [`docs/TOOLING.md`](docs/TOOLING.md)：现成工具调研，哪些直接用、哪些自己写
- [`docs/PRIOR_ART_AUDIT.md`](docs/PRIOR_ART_AUDIT.md)：前身项目 `anime-audio-classification-model` 的问题审计，作为「不要再犯」的记录

## 核心技术选择

| 环节 | 选定 |
| --- | --- |
| 人声分离 | `audio-separator` + Mel-Band Roformer |
| 说话人分离 | `pyannote/speaker-diarization-community-1` |
| 说话人嵌入 | `wespeaker-voxceleb-resnet293-LM`，对照组 ReDimNet-B2 |
| 聚类 | 两层：集内用 diarization 结果，跨集对 cluster 质心做 AHC |
| 音质闸门 | DNSMOS P.835 |

**一条贯穿全流程的红线**：16 kHz 只用于分析，成品永远从原始采样率音轨按时间戳切。音色模型多在 40 到 48 kHz 训练，搞错会让成品静默报废。

## 许可

TBD
