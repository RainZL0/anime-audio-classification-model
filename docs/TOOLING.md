# 现成工具调研

> 日期：2026-09-05
> 目的：在动手写代码前，确认哪些环节可以直接用现成组件，哪些必须自己写
> 配套文档：`DESIGN.md`

## 结论先行

**不要从零写。** 现成组件能覆盖管线的约 70%。真正没有现成方案、必须自己实现的只有一层：**跨集说话人链接 + 分组管理 + 原采样率导出**。

这直接改写了路线图：`DESIGN.md` 里的 M2（纵向打通）从「自己实现」降级为「组装现成组件」，省下的时间应全部投到 M3（跨集链接），那才是这个工具真正创造价值的地方。

## A. 可直接当依赖用

| 环节 | 选定 | 依据 |
| --- | --- | --- |
| 人声分离 | `audio-separator` + **Mel-Band Roformer** | Mel-Band 相对 BS-Roformer 在两种深度上各再拿 0.43 / 0.58 dB。具体检查点可直接抄 TTSizer 的 `kimmel_unwa_ft2_bleedless.ckpt`，`bleedless` 指低串音，正合我们的取舍：宁可损失一点人声，也不要漏 BGM 进成品 |
| 说话人分离 | `pyannote/speaker-diarization-community-1` | 相对 3.1，分割性能持平，说话人指派与计数明显改善。HF 上 gated，需接受条款 |
| 说话人嵌入 | `wespeaker-voxceleb-resnet293-LM` | TTSizer 的选择。与 pyannote 内部同一向量空间（pyannote 3.1 用的是较弱的 resnet34-LM），因此注册与 diarization 可共用嵌入。对照组用 ReDimNet-B2 |
| VAD | `silero-vad` | |
| 音质打分 | **DNSMOS P.835**，交叉验证用 `torchaudio.pipelines.SQUIM_*` | Emilia-Pipe 用 DNSMOS 做最终过滤，分离后均分 2.88 ± 0.50，过滤后 3.26 ± 0.14，方差大幅收窄。这组数字说明闸门确实有效 |
| 字幕解析 | `pysubs2` | |
| 音频 IO | `ffmpeg` + `soundfile` / `torchaudio` | |

## B. 参考实现：读代码抄思路，不整体依赖

### B.1 Emilia-Pipe（Amphion）★ 最完整的同类管线

六步：标准化、人声分离、说话人分离、VAD 细分、ASR、过滤。用 UVR-MDX-Net Inst 33 加 pyannote 3.1。是第一个开源的「野生语音转高质量训练数据」管线。

- **值得抄**：标准化的具体参数（单声道、16-bit、-20 dBFS）、DNSMOS 过滤的阈值设定方式、整体的阶段划分
- **不适用**：标准化会重采样到 **24 kHz**，对我们是有害的降采样；含 ASR，我们不需要；**没有跨文件说话人链接**，它只产出过滤后的片段，不按人分组

### B.2 TTSizer ★ 最接近我们的用例

AnimeVox 动画 TTS 语料就是用它做的，管线是：抽音轨 → 人声分离 → 响度归一 → 说话人分离 → 强制对齐 → 离群检测 → ASR 校验。

- **值得抄**：Mel-Band Roformer 的具体检查点、`wespeaker-resnet293-LM`、**离群检测**（就是 `DESIGN.md` 里的纯度自检）
- **不适用**：
  - **单文件设计**，文档未涉及跨集链接
  - 配置里要求预先写 `target_speaker_labels`，**也就是必须事先知道有谁**，与我们「可能零标签」的前提冲突
  - diarization 走 **Gemini API**，付费、不可离线、结果不可控
  - 无 GUI，无 review 环节

### B.3 AnimeSpeech（deeplearningcafe/animespeechdataset）

字幕驱动，用户手工标注部分台词 → 提嵌入 → KNN 加距离阈值预测其余台词。提供 SpeechBrain / WavLM / ESPnet 三种嵌入。

- 这基本是你旧代码的加强版：**要人工先标注**、**没有人声分离**。作为「不要这样做」的对照有价值
- 唯一值得留意的是它的字幕驱动流程，说明这条路走得通，只是天花板低

### B.4 其他

- **WhoSpeaks**：嵌入 + 余弦相似度 + 分组求平均消除异常，分组逻辑简单直接，可参考
- **Lukium/speaker-diarization-system**：CLI，把说话人拆成独立音轨，可参考输出组织方式
- **GPT-SoVITS / RVC 的 `tools/`**：内置 UVR5 与切片，可参考切片长度、静音处理、响度的工程细节

## C. review 界面：先评估现成的

`DESIGN.md` 的 M4 原计划自己写 Gradio。调研发现已有现成方案，应先评估：

- **voxmap-studio**（2026，开源）：说话人分离标注工具，turn 可以 resize、split、delete、create、reassign，并且明确支持**跨文件的 global speaker**。还有一个我原本没想到的好设计：**intrusion 标记**，把「与其他说话人更相似」的段自动高亮，把人的注意力引导到最可能标错的地方。这几乎就是 M4 的需求
- **GECKO**、**audino**：更通用的音频标注工具，同样支持 diarization 校正

**行动**：先花半天试 voxmap-studio。能用就省掉 1.5 天，而且它的 intrusion 标记比我原本设想的更好。注意：论文 PDF 里没给出仓库地址，需要先找到代码位置再评估。

## D. 确认没有现成方案的部分

这四项就是需要自己写的：

1. **跨集说话人链接。** pyannote 官方讨论区反复确认：说话人标签只在单次运行内一致，跨文件必须自己用嵌入匹配。调研到的所有管线工具（Emilia-Pipe、TTSizer 在内）都没做这一步。这是本工具的核心价值
2. **零标注、说话人数量未知的全系列聚类**，含长尾归并（`min_speaker_duration`）
3. **原采样率导出。** Emilia 降到 24 kHz，TTSizer 面向 TTS，都不保留原采样率。音色模型多在 40 到 48 kHz 训练，这是我们的硬需求
4. **动画特有的闸门**：歌唱段落检测（插入曲、角色歌）、重叠语音拒收

## E. 修订后的第一步

**在写任何代码之前，先手动跑通一次，回答一个问题：diarization 在动画音轨上到底能做到什么水平。**

```
1. audio-separator 分离你现有的那一集
2. pyannote community-1 diarize 分离后的人声
3. 听几个 cluster，人工估计纯度
```

半天成本，但这个数字决定后面所有投入的分配：

- 若 cluster 纯度已经不错 → 重心放在跨集链接与导出，review 只需轻量
- 若纯度差 → 先查前处理（分离质量、采样率、片段长度），再考虑 review 界面要做多重

在这个数字出来之前，不要开始写 M1 的工程骨架。
