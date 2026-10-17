# 竞品调研：从动画剧集中提取「按角色分类」语音片段的开源工具

调研日期：2026-10-18。星数与最后活跃时间取自 GitHub API（`pushed_at`，即最后一次推送），其余信息来自各项目 README、issue 列表与相关网页。

## 0. 结论先行

1. **这个细分领域几乎是空白。** 专门做「视频 + 字幕 → 按角色分好的音频/文本片段」的项目，星数最高的只有 55，大多数是 0～10 星，没有一个超过 150 星。星数真正高的（GPT-SoVITS 63k、RVC 39k、Fish Speech 33k）都是「训练端」，它们自带的数据准备功能完全没有「说话人是谁」这一维度。
2. **现有方案要么需要大量手工，要么依赖云端 API，要么在一次聚类后就结束，没有人在「纠错 → 模型变好」这个闭环上做事。** 带标注界面的只有 AnimeSpeech（Gradio，11 星，2024 年后无更新），而且作者自己写明「纠正预测很繁琐」。
3. **可直接复用的现成组件**：`litagin02/anime_speaker_embedding`（专为动画/视觉小说语音训练的 ECAPA-TDNN，23 星，2025-06 更新，有 `char` 与 `va` 两个版本）和 WeSpeaker（TTSizer、`anime-speaker-extraction` 都在用）。
4. **覆盖范围的限制（请注意）**：本次调研的搜索工具无法直接访问 Bilibili、知乎、X、note.com、Reddit 的站内搜索，这些平台只通过搜索引擎的间接结果覆盖到，**没有找到** 针对该问题的高热度帖子或视频。因此「用户抱怨」一栏里，来自这些平台的一手证据很少；这一点本身也说明：社区里大家是各自写脚本、没有公认的工具。

## 1. 竞品对比表

说明：「输入」中的「整集」指视频或整集音轨；「预切片」指已经切好的短音频。

### 1.1 直接竞品（按角色切分动画语音）

| 工具 | 星数 / 最后活跃 | 输入 | 说话人识别方式 | 标注/纠错界面 | 导出格式 | 主要问题与局限 |
|---|---|---|---|---|---|---|
| [deeplearningcafe/animespeechdataset](https://github.com/deeplearningcafe/animespeechdataset)（AnimeSpeech） | 11 星 / 2024-04 | 视频 + 字幕（无字幕时用 ReazonSpeech 转写） | **半监督**：先人工给部分字幕行标角色，用 SpeechBrain / WavLM / ESPnet 嵌入训练 KNN，距离阈值 0.2 内判定，超过 0.4 存疑 | **有**：Gradio（`webui_finder.py`） | CSV（预测、清洗）；对话数据集（LLM 用）与单角色音频+文本数据集（TTS 用） | README 自述：预测不完美、纠错「相当繁琐」；只能预测已建立表示的角色；依赖老旧（torch 2.0.1、gradio 4.20.1）；ESPnet 要 Docker；ASR 在 Windows 上需 WSL2；仅 1 个 issue，基本无人维护 |
| [N01N9/AniTTS-Builder-No-UI](https://github.com/N01N9/AniTTS-Builder-No-UI) | 7 星 / 2024-09 | `.mp4` + 同名 `.ass` 字幕，建议至少一季（约 12 集） | **无监督聚类**（Audio-separator 去背景 + SpeechBrain 嵌入） | 无（名字即「无界面版」） | 按说话人分文件夹的音频片段 | 只能靠聚类结果，聚类编号需人工对应角色；仅 Windows + Conda + CUDA 12；0 个 issue（几乎没人用） |
| [taresh18/TTSizer](https://github.com/taresh18/TTSizer) | 146 星 / 2025-08 | 视频或音频（整集） | 说话人分离（diarization）+ WeSpeaker 嵌入；**分离步骤调用 Google Gemini**；配置项 `target_speaker_labels`（Speaker1/2…） | 无，命令行 + YAML | 「对齐的音频-文本对」，按说话人分目录 | 必须有 Gemini API Key（云端、收费、有隐私顾虑）；需 >4GB 显存 GPU；模型权重要手动下载并改配置；README 无准确率数据；issue 里有「Requirements are wrong」。已被用于构建 [AnimeVox](https://github.com/taresh18/AnimeVox)（19 个英文配音角色、约 11k 条，CC BY-NC 4.0） |
| [Hecate2/sukasuka-vocal-dataset-builder](https://github.com/Hecate2/sukasuka-vocal-dataset-builder) | 55 星 / 2026-09 | MKV + `.ass` 字幕，可选 demucs 人声轨 | **纯手工**：贡献者在 `meta.csv`（`filename,character,content`）里逐条填角色 | 无（编辑 CSV） | `meta.csv`、按角色分文件夹的片段（`divide_by_character.py`） | 作者自述：标注繁琐费力；`meta.csv` 有已知错误；片段里混有非语音声音；短促无意义的叫声会损害训练 |
| [baduli5741/anime-speaker-extraction](https://github.com/baduli5741/anime-speaker-extraction) | 0 星 / 2026-07 | SRT 字幕（含部分说话人标记）+ 人声轨 | **半监督**：用带角色标记的字幕行求每个角色的质心（跨集合并），其余片段取最近质心，模糊的放进 `uncertain/`；标记与嵌入不一致则打 QA 标记 | 无 | 片段 + 嵌入 + 元数据 | 依赖「字幕本身带角色名」；README 里讲了许多环境坑（旧 GPU 的 cuDNN、uroman 的 perl 依赖、语言码必须用 `jpn`）；韩语文档，几乎无人知晓。**但其设计要点很值得参考**：字幕时间戳通常被延长 0.5～2 秒，直接切会咬到下一个说话人，所以要用 CTC 强制对齐 + VAD + 邻近字幕边界硬截断；跨集合并后再识别身份 |
| [dudqls5271/AnimeSpeaker](https://github.com/dudqls5271/AnimeSpeaker) | 0 星 / 2026-03 | 整集 `.mkv`（**不需要字幕**，Whisper 转写） | **无监督聚类**（pyannote，需要 HF token） | **有但很原始**：导出 `review/review.csv` 让用户编辑，再 `--finalize` | 按说话人整理的片段 + 元数据 | 仅 Windows PowerShell 脚本；要 HF token 和 CUDA；纠错靠编辑 CSV |
| [xiya-like/anime-voice-clip-extractor](https://github.com/xiya-like/anime-voice-clip-extractor) | 0 星 / 2026-10 | 整集音轨（用 yt-dlp 从 B 站下载） | **纯手工**：静音检测切出候选，在生成的 HTML 页面里勾选目标角色 | **有**：HTML 勾选页面 | 每句一个 wav、合并后的连续 wav | 完全手工；面向「某角色出场稀少」的场景；展示了社区的真实做法：下载音轨 → 静音切分 → 人耳挑选 |
| [blackhole077/pyannote_anime_speaker_diarization](https://github.com/blackhole077/pyannote_anime_speaker_diarization) | 0 星 / 2026-06 | 日语动画 | pyannote 说话人分离 | 未知 | 未知 | README 只有一行描述，无法判断完成度 |
| [Anime2Real/Chobits-Chii-Voice](https://github.com/Anime2Real/Chobits-Chii-Voice) | 0 星 / 2026-10 | —（这是成品数据集，不是工具） | 人工标注复听 | — | TV 全 24 集提取 487 段约 21.4 分钟 | 说明有人在发布「单角色成品数据集」，但流程是手工的 |

### 1.2 周边工具（做了一部分，不是为动画角色设计）

| 工具 | 星数 / 最后活跃 | 输入 | 说话人识别 | 标注界面 | 导出 | 主要问题与局限 |
|---|---|---|---|---|---|---|
| [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（内置数据工具） | 62,994 星 / 2026-10 | 预切片或长音频 | **无**（它假设你给的音频已经是单一说话人） | 有文本校对界面，**只校对文字，没有说话人维度** | `.list` | 内置：UVR5 人声分离、自动切片、ASR（中文用 FunASR，多语言用 Whisper）、文本标注。开放 issue 899 个。详见 §2 |
| [litagin02/Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2) | 1,387 星 / 2025-12 | 预切片 wav（`slice.py` 可切长音频，默认 2～12 秒） | 无 | 有 WebUI 的数据准备页，无说话人纠错 | `esd.list` | 转写默认 faster-whisper large-v3；多说话人需要自己把音频按人放好。详见 §2 |
| [Plachtaa/VITS-fast-fine-tuning](https://github.com/Plachtaa/VITS-fast-fine-tuning) | 5,001 星 / 2025-01（**已归档**） | 视频链接 / 上传的短音频 | 无（靠用户按说话人分别上传） | 无 | 自有格式 | 当年的「入门级」工具；issue 351 个，多是训练报错、路径问题；已归档，说明这个位置有人流失 |
| [openvpi/audio-slicer](https://github.com/openvpi/audio-slicer) | 887 星 / 2024-06 | 长音频 | 无（只按静音切） | GUI | wav 片段 | 常见的切片器，不判断说话人，多人对话和背景音乐会被一起切进去 |
| [pyannote/pyannote-audio](https://github.com/pyannote/pyannote-audio) | 10,661 星 / 2026-10 | 音频 | 说话人分离（无监督） | 无 | RTTM | 是 AnimeSpeaker、AnimeVox 一类流程的基础；用于动画的难点是背景音乐/音效、重叠说话、说话人数量需要预先给出（见知乎、CSDN 的通用教程里反复提到的问题） |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | 24,629 星 / 2026-09 | 音频 | 调用 pyannote | 无 | 带词级时间戳的转写 | 通用工具，对日语动画语音的说话人划分没有特殊处理 |
| [FlorianEagox/WeeaBlind](https://github.com/FlorianEagox/WeeaBlind) | 325 星 / 2024-11 | 视频 | diarization + 声音克隆 | GUI | 配音成品 | 目标是「自动配音」而非数据集；issue：Windows 依赖、不用 GPU、缺 License 文件 |
| [zacnami/gpt-sovits-character-voice](https://github.com/zacnami/gpt-sovits-character-voice) | 0 星 / 2026-10 | 素材音频 | 无，靠人/智能体检查边界与「其他说话人的声音」 | 无 | GPT-SoVITS 训练全流程 | 面向 AI 智能体的流程文档，反映了「切分后要人工检查混入其他说话人」是公认痛点 |
| [KagurazakaAsahi/voice-dataset-tool](https://github.com/KagurazakaAsahi/voice-dataset-tool) | 0 星 / 2026-05 | Galgame 已按角色整理好的音频 + 元数据 CSV | 不需要（输入已带角色） | 无 | GPT-SoVITS `.list`、train/val/test 划分 | 说明「导出 GPT-SoVITS 格式」是刚需；Galgame 因为游戏资源本身带角色标签，问题比动画简单得多 |

### 1.3 可复用的模型与数据

| 名称 | 星数 / 最后活跃 | 用途 | 备注 |
|---|---|---|---|
| [litagin02/anime_speaker_embedding](https://github.com/litagin02/anime_speaker_embedding) | 23 星 / 2025-06 | 在动画与视觉小说语音上训练的 ECAPA-TDNN 说话人嵌入（192 维） | `char` 版区分角色（同一声优的不同角色也分开），`va` 版区分声优；**可直接作为冻结编码器的候选**，与 WeSpeaker 对比即可 |
| [WeSpeaker](https://github.com/wenet-e2e/wespeaker) | 1,436 星 / 2026-09 | 通用说话人嵌入 | TTSizer、anime-speaker-extraction 都在用（ResNet293） |
| [litagin/anime-whisper](https://huggingface.co/litagin/anime-whisper) | — | 面向动画/游戏配音的日语 ASR | 见 §3 |
| [AnimeVox](https://github.com/taresh18/AnimeVox)、Anim-400K（[论文](https://arxiv.org/abs/2401.05314)） | — | 已有的角色标注数据集 | AnimeVox 是英文配音；Anim-400K 约 437k 条日语片段，说话人标签来自 pyannote，可用于评测但不适合直接训练具体角色 |

## 2. 训练端期望的数据集格式

| 项目 | 音频 | 文本/标注文件 | 说明 |
|---|---|---|---|
| **GPT-SoVITS** | 单说话人的短片段 wav | `.list` 文件，每行：`vocal_path|speaker_name|language|text`。语言码：`zh` / `ja` / `en` / `ko` / `yue`。示例：`D:\GPT-SoVITS\xxx/xxx.wav|xxx|zh|我爱玩原神.` | 官方文档写「1 分钟数据即可微调」。同一个 `.list` 可以含多个 `speaker_name`，所以**按角色导出多个 `.list`（或一个多角色 `.list`）就能直接接入**。日语训练要求根目录路径不含特殊字符 |
| **Style-Bert-VITS2** | 放在 `Data/{模型名}/raw/` 下的 wav（`slice.py` 默认切成 2～12 秒） | `Data/{模型名}/esd.list`，每行：`相对raw的wav路径|说话人名|语言|文本`，语言为 `JP` / `EN` / `ZH`（来自 `transcribe.py` 源码里的写法 `f"{wav_rel_path}|{model_name}|{language_id}|{text}\n"`） | 转写默认 faster-whisper `large-v3`；已有 `esd.list` 会被改名为 `esd.list.bak`。多说话人时需要在 `raw` 和 `esd.list` 中同时包含各说话人。文档里没有写「多少分钟够」的官方数字，社区文章多说 5～20 分钟起步 |
| **RVC** | **只要一个装满 wav 的文件夹**，不需要文本 | 无 | FAQ 建议总时长 10～50 分钟，高质量且音色有辨识度时 5～10 分钟也可；少于 1 分钟没有成功案例；剔除明显更小的（几乎无声）wav；路径中的空格和括号会让 FFmpeg 出错 |
| **Fish Speech** | 短片段音频 | 与音频同名的 `.lab` 文本文件（本次没有逐字核对其当前文档，**实现前请再查官方文档**） | 星数 33k，同样没有说话人归类能力 |

**对产品的含义**：导出器要支持三种目标——GPT-SoVITS 的 `.list`、SBV2 的 `esd.list`、RVC 的纯文件夹（外加通用的 `metadata.csv`）。因为三者都以「一个角色一份干净数据」为前提，**谁来保证每个文件夹里没有混进别人的声音，就是整个流程里最值钱的一步**。

## 3. 现在大家怎么获得日语台词文本

| 方式 | 说明 |
|---|---|
| **直接用字幕文件** | `.ass` / `.srt`，是最准确的台词来源（人工校对过），但时间戳不精确（通常被延长 0.5～2 秒）、常含多人同行和拟声词、有些字幕带角色名有些没有。AnimeSpeech、AniTTS-Builder、sukasuka 数据集构建器、anime-speaker-extraction 都以字幕为锚点 |
| **Whisper large-v3 / faster-whisper** | SBV2 默认；GPT-SoVITS 的多语言 ASR 也提供 Whisper。通用日语的字符错误率（CER）在动画语音上约 16.5%（见下） |
| **[litagin/anime-whisper](https://huggingface.co/litagin/anime-whisper)** | 以 kotoba-whisper-v2.0 为基础，在约 5,300 小时的 Galgame 语音上微调。作者报告 5 部未见过的视觉小说上平均 CER 13.0，对比 whisper-large-v3 为 16.5、kotoba-whisper-v2.0 为 18.8、reazonspeech-nemo-v2 为 23.6（均为作者自测）。**不要加 initial prompt**（会降质量）；出现重复幻觉时把 `no_repeat_ngram_size` 调到 5～10 |
| **kotoba-whisper / ReazonSpeech** | 日语通用的蒸馏模型与 NeMo 模型，速度快，但在动画语音上弱于 anime-whisper |
| **FunASR（SenseVoice / Paraformer）** | GPT-SoVITS 中文流程的默认选择，在中国社区常见 |
| **CTC 强制对齐** | 当字幕文本准确但时间不准时，用 CTC 对齐把时间戳修正到词级（`anime-speaker-extraction`、TTSizer 都用了） |

**对产品的含义**：因为我们要求「视频 + 字幕」作为必需输入，文本问题基本被字幕解决；真正要解决的是 **时间边界** 与 **说话人是谁**。anime-whisper 可以作为可选项，用来在字幕缺失或与音频不一致时校验。

## 4. 用户的主要抱怨（归纳）

下面这些来自 README 的自述、issue 标题和教程文章，不是对海量评论的统计。

1. **标注（谁说的）全靠人**：sukasuka、xiya-like 项目都是手填 CSV 或在 HTML 里勾选；AnimeSpeech 自己说纠错繁琐。
2. **聚类结果碎片化或编号不对应角色**：无监督方案（AniTTS-Builder、AnimeSpeaker）只给出「说话人 1、2、3…」，每集的编号还会变（`anime-speaker-extraction` 的说明明确指出了这一点）。
3. **背景音乐、音效、多人重叠** 会污染片段：zacnami 的流程特地要求检查「相邻对白和其他说话人的声音」；sukasuka 自述片段里混有非语音声音。
4. **字幕时间戳不准**：直接按字幕切会带入下一句。
5. **环境难装**：旧依赖（AnimeSpeech）、必须 Docker/WSL2、Conda + 特定 CUDA（AniTTS-Builder）、HF token（AnimeSpeaker）、云端 API Key（TTSizer）。VITS-fast-fine-tuning 的 351 个 issue 大多也是环境和路径问题。
6. **不能增量改进**：没有一个工具让「我纠正的错误」反过来改善下一集的预测。AnimeSpeech 有 KNN 但需要人先建好表示，且重新训练要走另一个 Web 界面。
7. **日语 ASR 不准**：Whisper 在动画语音（喘息、笑声、拟声词）上容易出现重复幻觉，anime-whisper 的存在本身就是对这一点的回应。

## 5. 我们能占据的空位（gaps we can own）

1. **「纠错即训练」的闭环。** 现有工具要么一次性输出（聚类、KNN 之后就结束），要么只能改 CSV。冻结的说话人编码器 + 轻量分类头可以做到「改几条 → 秒级重训 → 剩余预测立刻变好」。这是目前所有竞品都没有的体验，也是 README 里最适合放进 GIF 的画面。
2. **监督式（有名字的角色）替代无监督聚类。** 聚类给的是「说话人 3」，用户还得自己对应角色；用户先在前几集标几个样本，之后每集直接得到「角色名 + 置信度」。`anime-speaker-extraction` 已证明「字幕里的角色标记 + 质心」可行，但没有界面、没有人在维护、只有 0 星。
3. **把「视频 + 字幕」作为一等输入，并把字幕时间修正做好。** 字幕延长问题已有成熟方案（CTC 对齐 + VAD + 邻近字幕边界截断），但只存在于一个 0 星的韩语 README 里。做进默认流程就是明显的质量提升。
4. **本地、无云端 API、Windows 可用、`uv sync` 即可安装。** TTSizer 要 Gemini，AnimeSpeaker 要 HF token，AniTTS-Builder 要 Conda，AnimeSpeech 要 Docker。「一条命令装好、全部本地运行」本身就是卖点。
5. **一键导出三种训练格式。** GPT-SoVITS `.list`、SBV2 `esd.list`、RVC 文件夹，加上按角色划分的 train/val。目前每个项目只导出自己的一种格式（或自定义 CSV），用户还要自己写转换脚本（`KagurazakaAsahi/voice-dataset-tool` 就是这样一个例子）。
6. **跨集合并后再确定身份，并给出「不确定」队列。** 只让用户处理低置信度的片段，而不是逐条听完；这直接对应「标注工作量」这个最大的抱怨。
7. **使用 anime 专用嵌入作为卖点与可比较的基准。** 把 `anime_speaker_embedding`（`char` / `va`）与 WeSpeaker 在同一批动画数据上的准确率放进 README，没有任何竞品公布过这类数字。

### 需要警惕的点

- **目标用户并不多**：现有的同类项目星数都很低，说明需求被满足的方式是「各自写脚本」。想要 1k 星，关键不是功能多，而是 **演示效果直观**（上传一集 → 标 10 条 → 全集自动分好）和 **安装零摩擦**。
- **版权与声优授权**：AnimeVox 采用 CC BY-NC，多篇教程都提醒要看授权。README 里需要写清楚用途边界（个人研究，不分发提取出的音频）。
- **重叠说话与带背景音乐的片段** 是任何分类器都会出错的地方，需要有「丢弃/待定」状态，而不是强行分类。

## 6. 未完成或未核实的部分

- Bilibili、知乎、X、note.com、Reddit 的站内内容 **没有逐条检索到**。搜索引擎只返回了通用教程（pyannote、3D-Speaker、GPT-SoVITS 整合包）和两条相关线索：知乎问题「动漫里的人物原声如何干净提取？」（https://www.zhihu.com/question/364392496）、B 站的「BA 全角色日配语音数据集」分享（https://www.bilibili.com/video/BV1eJ4m1s7kq/），均未打开细读。若要写 README 的「用户痛点」引用，建议人工到这些平台补一轮。
- 各项目的星数以 2026-10-18 的 GitHub API 为准；`pushed_at` 可能包含 README 微调，不一定代表代码仍在更新。
- Fish Speech 的数据格式只凭印象写出，未对照当前官方文档。
- 各项目的实际识别准确率没有自行跑过，表中均为 README 自述。
