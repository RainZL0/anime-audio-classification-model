<div align="center">

# anime-voice-collector

[English](README.md) · **简体中文**

**把动画剧集整理成一个角色的语音数据集：干净的切片，每段都带台词，可直接用于 GPT-SoVITS、Style-Bert-VITS2 和 RVC。**

[![CI](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml/badge.svg)](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg?logo=windows&logoColor=white)](#支持的平台)

[快速开始](#快速开始) · [怎么标注](#怎么标注) · [导出格式](#导出格式) · [文档（英文）](docs/index.md) · [参与贡献（英文）](CONTRIBUTING.md)

<!-- 演示 GIF：上传到放图片的 issue，再把地址填在这里。git 里不存图片。 -->

</div>

## 为什么做这个

想训练某个角色的声音模型（GPT-SoVITS、Style-Bert-VITS2、RVC），需要这个角色单独说话的几分钟音频，每段还要配上台词。手工做就得把每一集从头拖到尾。多数工具只做到说话人分离（按声音像谁把台词分成几组），给每组起名字、逐条检查还是要你自己来。

在这里，你一边看画面一边标几条。一个小模型学会你的角色，把剩下的分好类，而且**每次你纠正它，几秒内就重新训练**，其他的猜测马上跟着更新。

## 功能

- 🎬 **按字幕切分。** 每句台词切成一段，不会因为语音检测漏掉台词。
- 🎤 **分离人声**，去掉每段里的音乐和音效。
- 🧠 **从你的纠正中学习。** 标出目标角色和「其他」，模型边标边更新。
- 📺 **边看边标。** 每句台词都配着视频播放，按一个键就能看前后更多内容。
- ⌨️ **以键盘操作为主**，可以撤销。
- 🈶 **台词用原声语言。** 用翻译字幕或双语字幕切分也可以；导出的文字始终是角色实际说的话，标注时每段也会显示它。
- 📦 **导出**为 GPT-SoVITS、Style-Bert-VITS2 格式，或每个角色一个文件夹（给 RVC 用），保持原始采样率。
- 🔒 **全部在本机运行。** 不上传任何东西。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/)（它会自动装好合适的 Python），以及 `PATH` 里能找到的 [FFmpeg](https://ffmpeg.org/)（`ffmpeg` 和 `ffprobe`）。强烈建议用 NVIDIA 显卡；没有的话，分离一集的人声要慢得多。

```bash
git clone https://github.com/RainZL0/anime-voice-collector.git
cd anime-voice-collector
uv sync --locked
uv run avoc doctor
```

`doctor` 会检查显卡、FFmpeg、人声分离模型、Hugging Face 令牌和剩余磁盘空间。标为缺失的项目请先补上。

**1. 把一集加入工作文件夹。** 需要这一集的视频和一个字幕文件（`.ass` 或 `.srt`），字幕要和对白对得上，最好是原声语言。一条命令完成人声分离、切分，以及标注界面需要的全部计算：

```bash
uv run avoc add workspace "Episode 01.mkv" --subs "Episode 01.ja.srt" --offset 0
```

| 选项 | 作用 |
| --- | --- |
| `--offset` | 字幕时间要加上的秒数，让字幕和音频对齐。同一个片源、同一个字幕组的各集，几乎总是同一个偏移：算一次，之后沿用。 |
| *（不加 `--offset`）* | 用 [pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1) 自动测量偏移。这个模型需要申请：先在 Hugging Face 上同意它的条款，再运行 `uv run hf auth login`。 |
| `--display-subs "Episode 01.zh.ass"` | 一份你看得懂的翻译，标注时显示在每句台词上方。不会从它导出任何内容。 |
| `--text-subs "Episode 01.ja.ass"` | 只在 `--subs` 是翻译字幕时使用：附上原声语言的字幕，导出的文字从这里取。这样会有不少切片拿不到文字，所以更推荐 `--subs` 直接用原声语言的字幕。 |
| `--spoken ja` | 原声语言（`ja`、`zh`、`en`、`ko`）。默认从音轨读取；双音轨的视频会选用对应的那条音轨。 |

如果中途停了（比如显存不够），再运行一次同样的命令，会从停下的地方继续。也可以在界面里添加剧集。

**2. 打开标注界面：**

```bash
uv run avoc app workspace
```

浏览器会打开 `http://127.0.0.1:8765`。

## 怎么标注

你只需要给想要的角色起名（目标角色）。其他人统一标为「其他」。目标角色可以随时增加或移除，已有的标注依然有效。

| 视图 | 按键 | 在这里做什么 |
| --- | :---: | --- |
| **起步分组** | `G` | 从这里开始。声音相近的切片分在一组，可以整组一起标。 |
| **场景** | `S` | 按顺序列出每句台词，同时播放视频。`Enter` 接受模型的猜测，数字键选目标角色，`Q` 表示「其他」，`Shift` + 数字键把这个角色的切片标为质量低（有背景噪声、几个人声音重叠）。 |
| **角色** | `O` | 模型分给某个角色的全部切片，最没把握的排在前面。改掉错的，再用 `Shift+Enter` 确认其余的。下方是模型可能漏掉的切片。 |
| **导出** | `E` | 写出数据集。 |

`Z` 撤销上一步。质量低的切片不参与训练，导出时也会跳过。运行 `uv run avoc --help` 查看所有命令；完整说明见 [docs/USAGE.md](docs/USAGE.md)（英文）。

## 导出格式

| 格式 | 输出 |
| --- | --- |
| GPT-SoVITS | 切片，以及带每句台词的 `train.list` |
| Style-Bert-VITS2 | 切片，以及带每句台词的 `esd.list` |
| 每个角色一个文件夹 | 纯音频切片，给 RVC 等不需要文字的工具用 |

切片从分离出的人声中切出，保持原始采样率。文字是原声语言。文字无法完整对上的切片不会导出，列在 `rejected.tsv` 里。

## 支持的平台

| 平台 | 状态 |
| --- | --- |
| Windows 11 + NVIDIA 显卡 | ✅ 已测试（RTX 4060 Laptop） |
| 没有显卡的 Windows | 用 CPU 运行，较慢 |
| Linux | ⚠️ 尚未测试。安装时已经会选用 CUDA 版的 torch。 |
| macOS | ⚠️ 尚未测试。只能用 CPU。 |

欢迎在 issue 里反馈 Linux 和 macOS 上的情况。

## 文档

工作原理、用到的术语，以及试过并已放弃的方案，见 [docs/index.md](docs/index.md)（英文）。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)（英文）。

## 使用规则

代码以 [MIT 许可证](LICENSE)发布。用它提取出的音频和文字属于原作品的权利人，不在 MIT 许可证的范围内。使用本工具即表示你同意：

- 提取的素材只用于个人研究或学习；
- 不把提取的音频、文字或用它们训练的模型用于任何商业用途；
- 不用提取的声音冒充角色或声优。

本节如与英文版有出入，以英文版为准。

## 致谢

本项目基于 [audio-separator](https://github.com/nomadkaraoke/python-audio-separator)、[anime-speaker-embedding](https://github.com/litagin02/anime_speaker_embedding)、[ReDimNet](https://github.com/PalabraAI/redimnet2)、[pyannote.audio](https://github.com/pyannote/pyannote-audio) 和 [pysubs2](https://github.com/tkarabela/pysubs2)。
