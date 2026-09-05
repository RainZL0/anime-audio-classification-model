# 选型与调研

> 本文档是**选型的唯一事实来源**：具体用哪个库、哪个模型、哪个检查点，以及为什么。
> 管线结构见 [`DESIGN.md`](DESIGN.md)，进度见 [`ROADMAP.md`](ROADMAP.md)，取舍理由见 [`DECISIONS.md`](DECISIONS.md)。
> 最后更新：2026-09-05

## 0. 调研结论

**不要从零写。** 现成组件能覆盖管线的约 70%。真正没有现成方案、必须自己实现的只有一层：**跨集说话人链接 + 分组管理 + 原采样率导出**（见第 4 节）。

这直接影响了排期：M2（纵向打通）从「自己实现」降级为「组装现成组件」，估时从 1.5 天下调到 0.5 天，省下的时间投到 M3（跨集链接）。

## 1. 已装入本项目的依赖

`uv sync` 后 `avs doctor` 验证通过的版本：

| 环节 | 包 | 已装版本 | 备注 |
| --- | --- | --- | --- |
| 深度学习 | `torch` / `torchaudio` | 2.11.0+cu128 | 按平台绑定 index，见 ADR-011 |
| 人声分离 | `audio-separator[gpu]` | 0.47.0 | onnxruntime-gpu 1.29 |
| 分离的隐藏依赖 | `audioread` | 3.1.0 | audio-separator import 时需要但**没有声明**，必须显式加 |
| 说话人分离 | `pyannote.audio` | 4.0.7 | |
| 字幕 | `pysubs2` | 1.9.0 | |
| 音频 IO | `soundfile` | 0.14.0 | |
| 表 | `pandas` / `pyarrow` | 3.0.5 / 25.0.1 | |
| CLI | `typer` / `rich` | 0.27.2 / 15.0.0 | |
| 配置 | `pydantic` / `pydantic-settings` | 2.13.5 / 2.15.0 | |

尚未装入、需要时再加：DNSMOS 打分（`speechmos` 或直接用 `torchaudio.pipelines.SQUIM_*`）、`silero-vad`、聚类用的 `scikit-learn`（已被 pyannote 间接带入 1.9.0）。

## 2. 模型选型

| 环节 | 选定 | 依据 |
| --- | --- | --- |
| 人声分离 | **Mel-Band Roformer**，检查点候选 `kimmel_unwa_ft2_bleedless.ckpt` | Mel-Band 相对 BS-Roformer 在两种深度上各再拿 0.43 / 0.58 dB。`bleedless` 指低串音，正合我们的取舍：宁可损失一点人声，也不要漏 BGM 进成品。该检查点是 TTSizer 的选择 |
| 说话人分离 | **`pyannote/speaker-diarization-community-1`** | 相对 3.1，分割性能持平，说话人指派与计数明显改善，另有 exclusive single-speaker 模式。**HF 上 gated，需接受条款并拿 token** |
| 说话人嵌入 | **`wespeaker-voxceleb-resnet293-LM`**，对照组 **ReDimNet-B2** | resnet293-LM 与 pyannote 内部同一向量空间（pyannote 3.1 用的是较弱的 resnet34-LM），注册与 diarization 可共用嵌入。VoxCeleb1-O 已接近饱和（SOTA 约 0.17% EER），模型在真人朗读语音上的排序到日语动画配音域完全可能颠倒，**必须双跑后按自己数据选** |
| 音质闸门 | **DNSMOS P.835**，交叉验证用 `torchaudio.pipelines.SQUIM_*` | BAK 分量直接度量背景干扰强度，是检测 BGM 残留的正确工具；SIG 度量语音失真，可捕捉分离伪影 |
| VAD | `silero-vad` | |

**排除的选项**：NeMo Sortformer（每段最多 4 说话人，动画场景常有 5 到 10 个角色）；UVR5 的 GUI（已停在 v5.6.x，只用于人工试听比较检查点，不进流水线）；PLDA 后端（对现代大间隔训练的嵌入器，cosine + AS-Norm 一般更好）。

## 3. 参考实现：读代码抄思路，不整体依赖

### 3.1 Emilia-Pipe（Amphion）★ 最完整的同类管线

六步：标准化、人声分离、说话人分离、VAD 细分、ASR、过滤。用 UVR-MDX-Net Inst 33 加 pyannote 3.1。是第一个开源的「野生语音转高质量训练数据」管线。

- **值得抄**：标准化的具体参数（单声道、16-bit、-20 dBFS）、DNSMOS 过滤的阈值设定方式。它给了一组有说服力的数字：分离后 DNSMOS 均分 2.88 ± 0.50，过滤后 3.26 ± 0.14，方差大幅收窄，说明质量闸门确实有效
- **不适用**：标准化会重采样到 **24 kHz**，对我们是有害的降采样（ADR-004）；含 ASR，我们不需要（ADR-003）；**没有跨文件说话人链接**，它只产出过滤后的片段，不按人分组

### 3.2 TTSizer ★ 最接近我们的用例

AnimeVox 动画 TTS 语料就是用它做的。管线：抽音轨 → 人声分离 → 响度归一 → 说话人分离 → 强制对齐 → 离群检测 → ASR 校验。

- **值得抄**：Mel-Band Roformer 的具体检查点、`wespeaker-resnet293-LM`、**离群检测**（就是 `DESIGN.md` 里的纯度自检思路）
- **不适用**：单文件设计，无跨集链接；配置里要求预先写 `target_speaker_labels`，**即必须事先知道有谁**，与我们「可能零标签」的前提直接冲突（ADR-009）；diarization 走 **Gemini API**，付费、不可离线、结果不可控；无 GUI，无 review 环节

### 3.3 其他

- **AnimeSpeech**（`deeplearningcafe/animespeechdataset`）：字幕驱动，用户手工标注部分台词 → 提嵌入 → KNN 加距离阈值预测其余。基本是前身项目的加强版：**要人工先标注**、**没有人声分离**。作为反面参照有价值，说明纯字幕驱动这条路走得通但天花板低
- **WhoSpeaks**：嵌入 + 余弦 + 分组求平均消除异常，分组逻辑简单直接
- **Lukium/speaker-diarization-system**：CLI，把说话人拆成独立音轨，可参考输出组织方式
- **GPT-SoVITS / RVC 的 `tools/`**：内置 UVR5 与切片，可参考切片长度、静音处理、响度的工程细节

## 4. 确认没有现成方案的部分

这四项必须自己写，也是本工具的价值所在：

1. **跨集说话人链接。** pyannote 官方讨论区反复确认：说话人标签只在单次运行内一致，跨文件必须自己用嵌入匹配。调研到的所有管线工具（Emilia-Pipe、TTSizer 在内）都没做这一步
2. **零标注、说话人数量未知的全系列聚类**，含长尾归并（ADR-010）
3. **原采样率导出**（ADR-004）。Emilia 降到 24 kHz，TTSizer 面向 TTS，都不保留原采样率
4. **动画特有的闸门**：歌唱段落检测（插入曲、角色歌）、重叠语音拒收

## 5. review 界面：先评估现成的

- **voxmap-studio**（2026，开源）：说话人分离标注工具，turn 可以 resize、split、delete、create、reassign，**明确支持跨文件的 global speaker**。还有一个原本没想到的好设计：**intrusion 标记**，把「与其他说话人更相似」的段自动高亮，把注意力引导到最可能标错的地方。这几乎就是 M4 的需求。**待解决**：论文 PDF 未给出仓库地址，需先找到代码
- **GECKO**、**audino**：更通用的音频标注工具，同样支持 diarization 校正

决策见 ADR-012。

## 6. 参考链接

- [Amphion / Emilia-Pipe](https://github.com/open-mmlab/Amphion/tree/main/preprocessors/Emilia)、[Emilia 论文](https://arxiv.org/pdf/2407.05361)
- [TTSizer](https://github.com/taresh18/TTSizer)
- [animespeechdataset](https://github.com/deeplearningcafe/animespeechdataset)、[WhoSpeaks](https://github.com/KoljaB/WhoSpeaks)、[Lukium/speaker-diarization-system](https://github.com/Lukium/speaker-diarization-system)
- [voxmap-studio 论文](https://arxiv.org/pdf/2606.26842)
- [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)、[跨文件说话人讨论](https://github.com/pyannote/pyannote-audio/discussions/1085)
- [Mel-Band RoFormer](https://arxiv.org/pdf/2310.01809)、[BS-RoFormer](https://arxiv.org/pdf/2309.02612)、[MVSEP 算法排行榜](https://mvsep.com/en/algorithms)
- [awesome-diarization](https://github.com/wq2012/awesome-diarization)
