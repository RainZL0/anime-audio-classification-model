<div align="center">

# anime-voice-collector

[English](README.md) · **简体中文**

**从整集动画里收集一个角色的声音：只有这个角色在说话的干净片段，每段都带着这句说的原话。可以直接拿去训练 GPT-SoVITS 或 RVC。**

[![CI](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml/badge.svg)](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg?logo=windows&logoColor=white)](#支持的平台)

[安装](#安装) · [加第一集](#加第一集) · [怎么标注](#怎么标注) · [得到什么](#得到什么) · [常见问题](#常见问题) · [文档（英文）](docs/index.md)

<!-- 演示 GIF：上传到放图片的 issue，再把地址填在这里。git 里不存图片。 -->

</div>

## 为什么做这个

想训练某个角色的声音模型，需要这个角色单独说话的几分钟音频，每段还要配上台词。手工做就得把每一集从头拖到尾。多数工具只做到说话人分离（按声音像谁把台词分成几组），给每组起名字、逐条检查还是要你自己来。

在这里，你一边看画面一边标几句。一个小模型学会你的角色，把剩下的分好类，而且**每次你纠正它，几秒内就重新训练**，其他的猜测马上跟着变好。你只需要检查它的结果，不用全部自己做。

## 功能

- 🎬 **每句字幕切成一段**，不会因为语音检测漏掉台词。
- 🎤 **只留人声**：每段里的音乐和音效都去掉了。
- 🧠 **从你的纠正中学习。** 给想要的角色起名，其他人一律是「其他」。
- 📺 **边看边标。** 每句台词都配着视频播放，按一个键就能看前后更多内容。
- ⌨️ **以键盘操作为主**，每一步都能撤销。
- 🈶 **导出角色说出口的原话。** 文字用原声语言，哪怕你标注时看的是译文。
- 📦 **导出**为每个角色一个文件夹（给 RVC），或带每句文字的 GPT-SoVITS 格式，音质和视频一样。
- 🔒 **全部在本机运行。** 不上传任何东西。

## 安装

需要 Windows、[uv](https://docs.astral.sh/uv/)（它会自动装好合适的 Python）和 [FFmpeg](https://ffmpeg.org/)。强烈建议用 NVIDIA 显卡；没有的话，去掉一集的音乐要慢得多。

还没装 uv 和 FFmpeg 的话，打开 PowerShell 运行：

```powershell
winget install astral-sh.uv
winget install Gyan.FFmpeg
```

然后新开一个终端，让它找到刚装的程序，再运行：

```bash
git clone https://github.com/RainZL0/anime-voice-collector.git
cd anime-voice-collector
uv sync --locked
```

`uv sync` 会下载所需的全部东西，大约 5 GB。想检查这台机器，运行 `uv run avoc doctor`：它会看显卡、FFmpeg 和剩余磁盘空间，缺什么会告诉你怎么补。

## 加第一集

每一集需要：

- **视频**（`.mkv`、`.mp4` 等）；
- **和对白对得上的字幕**（`.ass` 或 `.srt`），最好是原声语言的，比如日语动画就用日语字幕；
- 想要的话，再加一份**给你看的字幕**，比如译文。它只在标注时显示，不影响别的。

在你选的一个文件夹上启动界面，这里叫 `workspace`：

```bash
uv run avoc app workspace
```

浏览器里会打开添加一集的表单。选好文件，按「开始」：它会去掉音乐、切出每句台词、准备好标注要用的一切，过程中会显示进度。之后从集数菜单里用同样的方法加下一集。

**字幕偏移**是字幕时间和声音差了几秒。空着就会自动测。自动测用的是 [Hugging Face](https://huggingface.co) 上一个免费的模型，要先同意一次它的条款、建一个令牌；需要时表单里会写出步骤。之后同一片源、同一字幕组的集会自动填上同样的值。

## 怎么标注

你只需要给想要的角色起名（目标角色）。其他人一律是「其他」。目标角色可以随时增加或移除，已经标的都留着。

| 视图 | 按键 | 在这里做什么 |
| --- | :---: | --- |
| **机器分组** | `G` | 从这里开始。机器把听起来像同一个人的台词分成一组，可以一起标。它可能把几个人混在一组，所以先勾出同一个人的台词，再选是谁。 |
| **场景** | `S` | 按顺序列出每句台词，同时播放视频。`Enter` 接受机器的猜测，数字键选角色，`Q` 表示「其他」，`Shift` + 数字键把这句标为质量低（背景太吵、两个人同时说话）。 |
| **角色** | `O` | 机器分给一个角色的全部台词，最没把握的排在前面。改掉错的，再用 `Shift+Enter` 确认其余的。下方是它可能漏掉的台词。 |
| **导出** | `E` | 写出数据集。 |

一个角色标到二三十句，机器就开始猜。`Z` 撤销上一步，`?` 列出所有按键，「指南」按钮讲四个视图各做什么。完整说明见 [docs/USAGE.md](docs/USAGE.md)（英文）。

## 得到什么

```text
exports/2026-10-24/
├── Teio/
│   ├── ep01_00083.120000_00085.430000.wav
│   └── ...
├── train.list      （只有 GPT-SoVITS：路径|角色|语言|文字）
└── rejected.tsv    （没导出的句子和原因）
```

每段是一个角色的一句台词：只有人声、单声道、采样率和视频一样、音量统一。标了质量低的句子不会导出。导出 GPT-SoVITS 时，找不全原声语言文字的句子不导出。

## 常见问题

**能用翻译字幕吗？** 能。最好用原声语言的字幕切台词，但翻译字幕或双语字幕也行。要导出 GPT-SoVITS 的话，再在导出页给这些集配上原声语言的字幕。

**做到一半停了，比如显存不够。** 再加一次同一集，会从停下的地方继续。

**能用命令行吗？** 能：`uv run avoc add workspace "Episode 01.mkv" --subs "Episode 01.ja.srt"`。所有命令和选项见 `uv run avoc --help`；添加表单里也会写出对应你这个工作文件夹的命令。

## 支持的平台

| 平台 | 状态 |
| --- | --- |
| Windows 11 + NVIDIA 显卡 | ✅ 已测试（RTX 4060 Laptop） |
| 没有显卡的 Windows | 用 CPU 运行，较慢 |
| Linux | ⚠️ 尚未测试。安装时已经会选用 CUDA 版的 torch。 |
| macOS | ⚠️ 尚未测试。只能用 CPU。 |

欢迎在 issue 里反馈 Linux 和 macOS 上的情况。

## 文档

工作原理、用到的说法，以及试过并已放弃的方案，见 [docs/index.md](docs/index.md)（英文）。想参与的话，见 [CONTRIBUTING.md](CONTRIBUTING.md)（英文）。

## 使用规则

代码以 [MIT 许可证](LICENSE)发布。用它提取出的音频和文字属于原作品的权利人，不在 MIT 许可证的范围内。使用本工具即表示你同意：

- 提取的素材只用于个人研究或学习；
- 不把提取的音频、文字或用它们训练的模型用于任何商业用途；
- 不用提取的声音冒充角色或声优。

本节如与英文版有出入，以英文版为准。

## 致谢

本项目基于 [audio-separator](https://github.com/nomadkaraoke/python-audio-separator)、[anime-speaker-embedding](https://github.com/litagin02/anime_speaker_embedding)、[ReDimNet](https://github.com/PalabraAI/redimnet2)、[pyannote.audio](https://github.com/pyannote/pyannote-audio) 和 [pysubs2](https://github.com/tkarabela/pysubs2)。
