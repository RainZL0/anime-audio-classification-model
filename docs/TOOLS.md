# 用了哪些工具，为什么选它

> 具体用哪个库、哪个模型，只在这份文档里写，别处不要重复。
> 流程怎么走见 [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md)，进度见 [`STATUS.md`](STATUS.md)，选择的理由见 [`DECISIONS.md`](DECISIONS.md)。不认识的词查 [`GLOSSARY.md`](GLOSSARY.md)。
> 最后更新：2026-09-05

## 调研结论

**不用从零写。** 现成的东西能覆盖流程的七成左右。真正没有现成方案、必须自己动手的只有一块：**把各集的分组连起来、管理这些分组、按原采样率导出**（见第 4 节）。

这直接影响了排期：「跑通一遍」那个阶段从「自己实现」降级成「把现成的接起来」，预计时间从一天半降到半天，省下的时间投到跨集连接上。

## 1. 已经装好的依赖

`uv sync` 装完，`avs doctor` 验证通过的版本：

| 干什么用的 | 包 | 装的版本 | 备注 |
| --- | --- | --- | --- |
| 深度学习框架 | `torch` / `torchaudio` | 2.11.0+cu128 | 按操作系统分别指定下载源，见决策 11 |
| 抠人声 | `audio-separator[gpu]` | 0.47.0 | 带 onnxruntime-gpu 1.29 |
| 抠人声的隐藏依赖 | `audioread` | 3.1.0 | `audio-separator` 导入时需要它，但自己没声明，必须手动加 |
| 切段认人 | `pyannote.audio` | 4.0.7 | |
| 读字幕 | `pysubs2` | 1.9.0 | |
| 读写音频 | `soundfile` | 0.14.0 | |
| 表格 | `pandas` / `pyarrow` | 3.0.5 / 25.0.1 | |
| 命令行 | `typer` / `rich` | 0.27.2 / 15.0.0 | |
| 配置 | `pydantic` / `pydantic-settings` | 2.13.5 / 2.15.0 | |

还没装、用到再加：音质打分（`speechmos`，或者直接用 torchaudio 自带的 `SQUIM`）、静音检测 `silero-vad`。分组要用的 `scikit-learn` 已经被 pyannote 顺带装进来了（1.9.0）。

## 2. 选了哪些模型

| 干什么用的 | 选定 | 为什么 |
| --- | --- | --- |
| 抠人声 | **Mel-Band Roformer**，候选检查点 `kimmel_unwa_ft2_bleedless.ckpt` | 这一类模型是目前效果最好的。Mel-Band 版本比它的前身 BS-Roformer 在两种规模下分别再好 0.43 和 0.58 分贝。`bleedless` 是指「串音少」，正合我们的取舍：宁可人声损失一点，也不要让背景音乐漏进成品。这个检查点是 TTSizer 用的 |
| 切段认人 | **`pyannote/speaker-diarization-community-1`** | 比上一版 3.1 好在「判断这段是谁」和「一共有几个人」上，切段本身的准确度持平，另外多了一个 exclusive 模式。**别误解这个模式**：它只是把同时说话人数强行截到 1、让标签不再重叠，音频里两个人还在，不能拿它当「已经没有重叠」用，细节见决策 14 |
| 声音指纹 | **`wespeaker-voxceleb-resnet293-LM`**，另跑一个 **ReDimNet-B2** 做对照 | resnet293 跟 pyannote 内部用的是同一套向量空间（pyannote 3.1 内部用的是较弱的 resnet34），所以两边能共用。另外要提醒的是：这类模型在标准评测集上已经卷到很难分高下了（最好的错误率约 0.17%），而它们都是拿真人说话训练的，到了日语动画配音这个场景，排名完全可能反过来。**所以必须两个都跑，用自己的数据选** |
| 音质打分 | **DNSMOS**，另用 torchaudio 的 `SQUIM` 交叉验证 | 它的 BAK 分直接反映背景干扰有多强，正好用来查背景音乐残留；SIG 分反映人声本身有没有被处理坏，用来查抠人声的伪影 |
| 静音检测 | `silero-vad` | |

**排除掉的选项**：

- **NeMo Sortformer**：每段最多只能处理 4 个说话人，而一集动画常有 5 到 10 个角色。
- **UVR5 的图形界面**：版本停在 v5.6.x 很久了，以后只用它来试听比较不同检查点，不放进流程。
- **PLDA 这类打分后端**：对现在这些用大间隔方式训练出来的指纹模型，直接算余弦相似度加分数归一化通常效果更好。

## 3. 值得读代码借鉴的项目

### 3.1 Emilia-Pipe（属于 Amphion 项目）

同类里最完整的一条流程，六步：标准化、抠人声、切段认人、静音细分、语音转文字、筛选。用的是 UVR-MDX-Net Inst 33 加 pyannote 3.1。它是第一个开源的「把网上找来的乱七八糟语音变成高质量训练数据」的流程。

**能借鉴的**：标准化的具体参数（转单声道、16 位、音量调到 -20 dBFS），以及筛选分界线怎么定。它给了一组挺有说服力的数字：抠完人声，音质平均分是 2.88（上下浮动 0.50）；再经过筛选，变成 3.26（上下浮动 0.14）。浮动范围大幅收窄，说明筛选这一步确实有用。

**不能照抄的**：它会统一转成 24 kHz，对我们来说这是有害的降采样（决策 4）；它带语音转文字，我们不需要（决策 3）；而且**它不做跨文件的人物连接**，只输出筛选过的片段，不按人分组。

### 3.2 TTSizer

跟我们的用途最接近的一个，AnimeVox 那套动画语音语料就是用它做的。流程是：抽音轨 → 抠人声 → 调音量 → 切段认人 → 文字对齐 → 挑出异常 → 语音转文字核对。

**能借鉴的**：Mel-Band Roformer 的具体检查点、`wespeaker-resnet293-LM` 这个指纹模型，以及「挑出异常」这一步的思路。

**不能用的**：

- 它是**按单个文件设计的**，不做跨集连接。
- 配置文件里**要求事先写死有哪些角色**，跟我们「可能一个标签都没有」的前提直接冲突（决策 9）。
- 切段认人走的是 **Gemini 的付费接口**，不能离线跑，结果也不可控。
- 没有界面，没有人工修改环节。

### 3.3 其他

- **AnimeSpeech**（`deeplearningcafe/animespeechdataset`）：靠字幕驱动，让使用者先手工标一部分台词，提取指纹，再用「离得近就算同一个人」的方式预测其余台词。基本上是上一版项目的加强版：**要人工先标注**、**不抠人声**。当反面参照有价值，它说明纯靠字幕这条路走得通，但天花板不高。
- **WhoSpeaks**：提指纹、算余弦相似度、分组时取平均消除异常值，思路简单直接。
- **Lukium/speaker-diarization-system**：命令行工具，把不同说话人拆成独立音轨，输出怎么组织可以参考。
- **GPT-SoVITS 和 RVC 里的 `tools/`**：内置了 UVR5 和切片工具，切片长度、静音怎么处理、音量怎么调，这些工程细节可以参考。

## 4. 确认没有现成方案的部分

下面四件事必须自己写，这也是这个工具存在的意义：

1. **把各集的分组连起来。** pyannote 官方讨论区反复说过：说话人编号只在单次处理内部有效，跨文件必须自己拿指纹去匹配。调研到的所有流程工具（包括 Emilia-Pipe 和 TTSizer）都没做这一步。
2. **在没有标签、也不知道有几个人的情况下给整部动画分组**，还要处理只说一两句的路人（决策 10）。
3. **按原采样率导出**（决策 4）。Emilia 转 24 kHz，TTSizer 面向语音合成，都不保留原采样率。
4. **动画特有的筛选**：唱歌段落检测（插入曲、角色歌）、两人重叠淘汰。

## 5. 人工修改界面：先看现成的

- **voxmap-studio**（2026 年，开源）：能调整边界、拆分、删除、新建、重新指派，**明确支持跨文件的统一人物编号**。还有一个我们原本没想到的好设计：自动高亮那些「跟别的组更像」的片段，把注意力引到最可能标错的地方。这基本就是我们的需求。**待解决**：论文里没给仓库地址，得先找到代码。
- **GECKO**、**audino**：更通用的音频标注工具，也支持修正说话人分段结果。

对应的选择记在决策 12。

## 6. 参考链接

- [Amphion / Emilia-Pipe](https://github.com/open-mmlab/Amphion/tree/main/preprocessors/Emilia)、[Emilia 论文](https://arxiv.org/pdf/2407.05361)
- [TTSizer](https://github.com/taresh18/TTSizer)
- [animespeechdataset](https://github.com/deeplearningcafe/animespeechdataset)、[WhoSpeaks](https://github.com/KoljaB/WhoSpeaks)、[Lukium/speaker-diarization-system](https://github.com/Lukium/speaker-diarization-system)
- [voxmap-studio 论文](https://arxiv.org/pdf/2606.26842)
- [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)、[关于跨文件说话人的讨论](https://github.com/pyannote/pyannote-audio/discussions/1085)
- [Mel-Band RoFormer 论文](https://arxiv.org/pdf/2310.01809)、[BS-RoFormer 论文](https://arxiv.org/pdf/2309.02612)、[MVSEP 算法对比榜](https://mvsep.com/en/algorithms)
- [说话人分段资料汇总](https://github.com/wq2012/awesome-diarization)
