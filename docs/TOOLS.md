# 用了哪些工具，为什么选它

> 具体用哪个库、哪个模型，只在这份文档里写，别处不要重复。
> 流程怎么走见 [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md)，进度见 [`STATUS.md`](STATUS.md)，选择的理由见 [`DECISIONS.md`](DECISIONS.md)。不认识的词查 [`GLOSSARY.md`](GLOSSARY.md)。
> 最后更新：2026-09-06（当天第二次，见第 7 节）

## 调研结论

**不用从零写。** 现成的东西能覆盖流程的七成左右。真正没有现成方案、必须自己动手的只有一块：**把各集的分组连起来、管理这些分组、按原采样率导出**（见第 4 节）。

这直接影响了排期：「跑通一遍」那个阶段从「自己实现」降级成「把现成的接起来」，预计时间从一天半降到半天，省下的时间投到跨集连接上。

**2026-09-06 复查过一次这些选型还算不算又流行又前沿，见第 6 节。** 结论是三步照旧不换，音质筛选留了一个候选。

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
| 抠人声 | **Mel-Band Roformer**，检查点 `kimmel_unwa_ft2_bleedless.ckpt`（在 `audio-separator` 里叫 `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`） | `bleedless` 是指「串音少」（见 [`GLOSSARY.md`](GLOSSARY.md)），正合我们的取舍：宁可人声损失一点，也不要让背景音乐漏进成品。这个检查点是 TTSizer 用的。**选它的依据只有这两条，拿不出任何质量数字**，复查见第 6.1 节 |
| 切段认人 | **`pyannote/speaker-diarization-community-1`** | 比上一版 3.1 好在「判断这段是谁」和「一共有几个人」上，切段本身的准确度持平，另外多了一个 exclusive 模式。**别误解这个模式**：它只是把同时说话人数强行截到 1、让标签不再重叠，音频里两个人还在，不能拿它当「已经没有重叠」用，细节见决策 14 |
| 声音指纹 | **ReDimNet2 B6**（前沿臂），另跑 **`wespeaker-voxceleb-resnet293-LM`**做对照（稳妥臂）。**已实测选定，见决策 17** | resnet293 跟 pyannote 内部用的是同一套向量空间（pyannote 3.1 内部用的是较弱的 resnet34），所以两边能共用。另外要提醒的是：这类模型在标准评测集上已经卷到很难分高下了（最好的错误率约 0.17%），而它们都是拿真人说话训练的，到了日语动画配音这个场景，排名完全可能反过来。**所以必须两个都跑，用自己的数据选** |
| 音质打分 | **实际用的是 torchaudio 自带的 `SQUIM`**（决策 15），DNSMOS 退为备选 | 选 SQUIM 是因为不用额外授权、torchaudio 已经装了。但它针对的是电话噪声、编码损伤这类问题，不是「背景有一群人在喊」，所以只是够用，不是最合适的。替代候选见第 6.4 节 |
| 静音检测 | `silero-vad` | |

**排除掉的选项**：

- **NeMo Sortformer**：每段最多只能处理 4 个说话人，而一集动画常有 5 到 10 个角色。2026-09-06 复查，这条依然成立，基准测试还补充说 Sortformer 系随人数增加而变差。但有一条反直觉的发现值得记下来：**Sortformer v2 在日语上是所有模型里最好的**（分段错误率 12.7%，比付费的 pyannoteAI 还好），而我们做的正是日语动画。人数上限是硬伤，还是用不了，但它说明「日语场景下谁更强」跟通用排行榜可能不是一回事。
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
- **AniSpeech**（`ShoukanLabs/AniSpeech`）：另一个动画语音语料。如果它公开了制作流程，就是继 AnimeVox 之后第二个可比对象。**还没看过，值得花半小时。**
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

## 6. 选型复查（2026-09-06）

第 2 节那批选择是 2026-09-05 定的，定完之后一直没查过它们在社区里还算不算又流行又前沿。这次逐步查了一遍。**决定见决策 16，这里只放查到的事实。**

### 6.1 抠人声：最强的两个拿不到，够得着的没一个能证明更好

按分离质量分（SDR，见 [`GLOSSARY.md`](GLOSSARY.md)）排，现在是三层格局：

| 层 | 代表 | 人声 SDR | 我们能不能用 |
| --- | --- | --- | --- |
| 最强 | BS Roformer 124 bands、BS PolarFormer | 12.33 / 12.02 | **不能**。MVSEP 那个付费网站独占，没有可下载的权重 |
| 公开权重最强 | BS-Roformer-Leap（unwa） | 11.72 | 能，但不在 `audio-separator` 内置清单里，要自己弄权重和配置文件 |
| 我们在用 | Mel-Band Roformer kim ft2 bleedless | **查不到** | 在用 |

`audio-separator` 0.47.0 内置 89 个模型，其中够得着、改一个常量就能换的现代候选只有四个：

| 检查点 | 谁做的 |
| --- | --- |
| `bs_roformer_vocals_revive_v2_unwa.ckpt` | unwa，跟我们现在这个同一条低串音路线 |
| `bs_roformer_vocals_revive_v3e_unwa.ckpt` | unwa |
| `mel_band_roformer_vocals_becruily.ckpt` | becruily |
| `mel_band_roformer_vocals_fv7b_gabox.ckpt` | Gabox |

社区参考手册 MSST Bible（2025-09 更新）现在推荐的是 becruily 的 Deux 和 Gabox 的 v10 Flowers，**这两个都不在内置清单里**，而且手册里完全没有提到我们用的 kim ft2。

**三条查证结果，记下来免得以后按错误信息决策：**

1. **第 2 节原来那句「Mel-Band 比 BS-Roformer 好 0.43 和 0.58 分贝」要加限定。** 那是论文在受控条件下比架构得出的，而现实排行榜的第一名恰恰是 BS-Roformer 的变种，因为实际效果更多取决于训练数据和规模。别读成「Mel-Band 就是比 BS 强」。
2. **网上流传的「Revive 2 的串音分是所有人声模型里最高的」查无实据。** 去社区手册原文核对过，没有这个说法，Revive 系列的任何具体分数都没有。
3. **我们这个检查点在 `audio-separator` 自带的分数表里没有质量分，但 becruily、Gabox FV 系列、Revive 也全都没有。** 那张表停更了，不是在挑我们。

**最要紧的一点：这些模型全都只分「人声 vs 伴奏」，对我们真正的病因（群体人声，见 [`STATUS.md`](STATUS.md)）一个都治不了。** 换模型的预期收益接近零，这是不换的主要理由。

### 6.2 切段认人：DiariZen 是唯一一个真正的升级候选

| 层 | 谁 | 分段错误率（DER，见 [`GLOSSARY.md`](GLOSSARY.md)） | 我们能不能用 |
| --- | --- | --- | --- |
| 最好 | pyannoteAI 付费接口 | 11.2% | 不能，付费且要联网 |
| 开源最好 | **DiariZen** | 13.3%（VoxConverse 上 9.1%） | 能 |
| 我们在用 | pyannote community-1 | VoxConverse 上 11.2% | 在用 |

DiariZen（`BUTSpeechFIT/DiariZen`）537 个星，2026-01 还在更新，有现成的 HuggingFace 管线 `BUT-FIT/diarizen-wavlm-large-s80-md`。做法是拿剪枝过的 WavLM 大模型当前端，后面接 Conformer 和 VBx 聚类。

**两条代价：**

1. **它自带一个 pyannote-audio 的分支，用 git 子模块加版本约束安装**，跟我们装的 pyannote.audio 4.0.7 大概率打架，得单开一套环境。不是改一行的事。
2. **它同样是拿会议录音训练的**，群众欢呼在它眼里同样不算「另一个说话人」。它能改善边界准度和「这段是谁」，那对分组有用，但不会让第一轮试听里那些片段变合格。

### 6.3 整理候选片段：确认没有可比的现成方案

- Emilia-Pipe 用 `silero-vad` 按静音重新切一遍，目的是切出适合语音合成的长度
- TTSizer 靠剧本文字对齐来定边界
- **两家都没有「在换人处向内让出安全距离」这个动作**

而那正是我们这一步的核心（决策 14）。没有库可换，也不用换。这一步真正的风险不是缺库，是那几个默认值全是照第 1 集调出来的，`build_segments()` 的注释里已经写了换素材要重新看。

### 6.4 音质筛选：Audiobox-Aesthetics 是最划算的一次尝试

现在用的 SQUIM 在这一行里是个异类：它是唯一一个需要「不匹配参考音频」的打分方式，而且针对的是电话噪声、编码损伤、混响这类问题，**不是「背景有一群人在喊」**。这跟实测对得上（决策 15：7 条不合格片段里抓到 5 条）。

前人用的是 DNSMOS（Emilia-Pipe）。

现在流行度和前沿度都够的是 **Meta Audiobox-Aesthetics**（`facebookresearch/audiobox-aesthetics`）：

- 756 个星，`pip install audiobox_aesthetics` 就装得上，没有授权门槛
- 输出四个维度，其中**制作质量（PQ）**最接近我们要的「这段录音干不干净」
- 2025 年的 AudioMOS 挑战赛专门设了一个赛道来预测它这四个维度，说明行业已经把它当标准看
- 论文对比显示它跟 DNSMOS、UTMOSv2 的相关性水平相当

**为什么划算：尺子是现成的。** 第 1 集那 7 条人工标注的不合格片段还在，决策 15 里那张「抓到了吗」的表就能直接拿来量。装上跑一遍同一批 180 条，看那 7 条排在什么位置，跟 SQUIM 比。半天的活，出来的是硬结果，不是转述别人的排行榜。

要有心理准备：它同样抓不到「两个清晰人声」那一族。但它有机会在「群众声、杂音」那一族上比 SQUIM 准，而那族占了 7 条里的 5 条。

### 6.5 复查新增的参考读物

- **Speaker Diarization of Scripted Audiovisual Content**（arXiv 2308.02160）：直接针对影视剧这类有剧本的内容做说话人分段。它点了一件跟我们有关的事：**说话人多的时候，谱聚类会严重低估人数。** 第 5 阶段定相似度分界线时可以拿它当先验。
- **`voxmap-studio` 的仓库仍然找不到**，详见 [`STATUS.md`](STATUS.md) 的未决问题。

## 7. 指纹模型：实测选定（2026-09-06）

第 6 节的复查只看了抠人声、切段认人、音质筛选三步，没查声音指纹。这次补上，而且**跑了真数据**，
不是照排行榜挑的。决定和理由见决策 17。

| 模型 | 声纹错误率（VoxCeleb1-O） | 参数量 | 状态 |
| --- | --- | --- | --- |
| **ReDimNet2 B6** | **0.287%** | 12.3M | **选定，前沿臂** |
| WeSpeaker ResNet293-LM | 0.447% | 大得多 | 选定，稳妥臂 |
| ReDimNet B2（原计划的对照） | 0.57% | 3.6M | 被 ReDimNet2 取代 |

ReDimNet2 是 Interspeech 2026 的，2026-07-01 发布，2026-07-03 就被 WeSpeaker 收编，
这比它 87 个星更能说明被采纳的程度。MIT 许可，只要 torch 和 torchaudio。

**在我们自己的素材上，两个的差距比公开评测小得多**：公开评测差三分之一，实测只差
0.861 对 0.844（分得开程度）。方向一致，幅度被压扁了。这正是第 2 节那条「必须两个都跑，
用自己的数据选」的意义，别指望换模型带来大改善。

**两个用起来的坑，代码注释里也写了：**

1. **ReDimNet2 只能走 `torch.hub`，没有 pip 包。** 它会从 GitHub 拉代码并执行，必须显式传
   `trust_repo=True`，否则脚本会卡在等你敲确认。
2. **WeSpeaker 那条走 onnxruntime，本机的 onnxruntime-gpu 跟 torch 的 CUDA 版本对不上**
   （见 `STATUS.md` 的踩坑记录），所以固定按 CPU 跑。90 条片段几秒钟，不值得为它折腾版本。
   另外 pyannote 的加载器默认找 `speaker-embedding.onnx`，而那个仓库里文件叫
   `voxceleb_resnet293_LM.onnx`，得自己先下下来再把本地路径递给它。

## 8. 参考链接

- [Amphion / Emilia-Pipe](https://github.com/open-mmlab/Amphion/tree/main/preprocessors/Emilia)、[Emilia 论文](https://arxiv.org/pdf/2407.05361)
- [TTSizer](https://github.com/taresh18/TTSizer)
- [animespeechdataset](https://github.com/deeplearningcafe/animespeechdataset)、[WhoSpeaks](https://github.com/KoljaB/WhoSpeaks)、[Lukium/speaker-diarization-system](https://github.com/Lukium/speaker-diarization-system)
- [voxmap-studio 论文](https://arxiv.org/pdf/2606.26842)
- [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)、[关于跨文件说话人的讨论](https://github.com/pyannote/pyannote-audio/discussions/1085)
- [Mel-Band RoFormer 论文](https://arxiv.org/pdf/2310.01809)、[BS-RoFormer 论文](https://arxiv.org/pdf/2309.02612)、[MVSEP 算法对比榜](https://mvsep.com/en/algorithms)
- [说话人分段资料汇总](https://github.com/wq2012/awesome-diarization)
- 指纹模型：[ReDimNet2](https://github.com/PalabraAI/redimnet2)、[ReDimNet](https://github.com/IDRnD/redimnet)、[WeSpeaker ResNet293-LM](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet293-LM)
- 2026-09-06 复查新增：[MVSEP 多曲目排行榜](https://mvsep.com/quality_checker/multisong_leaderboard?sort=vocals)、[MSST Bible 社区手册](https://msst-bible.pages.dev/)、[DiariZen](https://github.com/BUTSpeechFIT/DiariZen)、[Audiobox-Aesthetics](https://github.com/facebookresearch/audiobox-aesthetics)、[AudioMOS 挑战赛 2025](https://arxiv.org/pdf/2509.01336)、[有剧本内容的说话人分段](https://arxiv.org/pdf/2308.02160)、[AniSpeech](https://huggingface.co/datasets/ShoukanLabs/AniSpeech)、[分段模型基准与失效模式 2026](https://kili-technology.com/blog/speaker-diarization-models-guide-benchmarks-and-failure-modes-2026)
