<div align="center">

# anime-voice-collector

**English** · [简体中文](README.zh.md)

**Collect one anime character's voice from whole episodes: clean clips of only them speaking, each with the words they said. Ready to train GPT-SoVITS or RVC.**

[![CI](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml/badge.svg)](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg?logo=windows&logoColor=white)](#platforms)

[Install](#install) · [Your first episode](#your-first-episode) · [Labeling](#labeling) · [What you get](#what-you-get) · [Questions](#questions) · [Docs](docs/index.md)

<img src="https://github.com/user-attachments/assets/6de411ae-34b0-4d17-b90a-2ac3ba3c170d" width="800" alt="Demo: name a group of lines as a character, the machine starts guessing the rest, fix a wrong guess, check the character's list, and export">

</div>

## Why

To train a voice model of one character, you need minutes of that character speaking alone, each clip with its line. By hand, that means scrubbing through every episode. Most tools stop at speaker diarization (grouping lines by which voice they sound like) and leave naming and checking the groups to you.

Here you label a few lines while watching the scene. A small model learns your character, sorts the rest, and **retrains in a few seconds every time you correct it**, so its other guesses improve right away. You check its work instead of doing all of it.

## Features

- 🎬 **One clip per subtitle line,** so no line is lost to a speech detector.
- 🎤 **Voice only:** music and sound effects are removed from every clip.
- 🧠 **Learns from your corrections.** Name the characters you want; everyone else is "Other".
- 📺 **Label while watching.** The video plays with each line, with more context one key away.
- ⌨️ **Keyboard first,** and every step can be undone.
- 🈶 **The words actually said.** The exported text is in the language spoken, even if you read a translation while labeling.
- 📦 **Export** one folder per character for RVC, or GPT-SoVITS with each line's text, at the quality of the video.
- 🔒 **Runs on your machine.** Nothing is uploaded.

## Install

You need Windows, [uv](https://docs.astral.sh/uv/) (it installs the right Python for you) and [FFmpeg](https://ffmpeg.org/). An NVIDIA graphics card is strongly recommended; without one, removing the music from one episode takes much longer.

If you don't have uv and FFmpeg yet, the easiest way is [Scoop](https://scoop.sh). Open PowerShell (not as administrator) and run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
scoop install uv ffmpeg
```

The first two lines install Scoop; skip them if you have it. You can also install FFmpeg yourself: download the Windows build from [ffmpeg.org](https://ffmpeg.org/download.html), unzip it, and add its `bin` folder to the `PATH` environment variable.

Then open a new terminal, so it finds them, and run:

```bash
git clone https://github.com/RainZL0/anime-voice-collector.git
cd anime-voice-collector
uv sync --locked
```

`uv sync` downloads everything, about 5 GB. To check the machine, run `uv run avoc doctor`: it looks at the graphics card, FFmpeg and free disk space, and says how to fix anything missing.

## Your first episode

For each episode you need:

- **the video** (`.mkv`, `.mp4`, …);
- **main subtitles** whose lines match the dialogue (`.ass` or `.srt`); each line becomes one clip. They are best in the language spoken, such as Japanese subtitles for a Japanese anime;
- if you like, **secondary subtitles** you can read, such as a translation. They are shown in small type under each line while labeling and change nothing else.

Start the app on a folder of your choice, here `workspace`:

```bash
uv run avoc app workspace
```

It opens in your browser and shows the form to add an episode. Pick the files and press Start: it removes the music, cuts the lines and gets everything ready, with its progress shown as it goes. Then add the next episodes the same way, from the episode menu.

**The subtitle offset** is how many seconds the subtitle times are off from the sound. Leave it empty and it is measured for you. Measuring uses a free [Hugging Face](https://huggingface.co) model that asks you to accept its terms and make a token once; the form shows the steps when they are needed. Later episodes from the same video source and subtitle group get the same value filled in.

## Labeling

You only name the characters you want (the target characters). Everyone else is "Other". You can add or remove target characters at any time, and the labels you made stay.

| View | Key | What you do there |
| --- | :---: | --- |
| **Groups** | `G` | Start here. The machine puts lines that sound like the same person into a group, so you can label them all at once. It may mix people up, so you tick the lines of one person before picking who it is. |
| **Scenes** | `S` | Every line in order, with the video playing. `Enter` accepts the machine's guess, a number picks a character, `Q` means "Other", `Shift` + number marks the line low quality (loud background, two people at once). |
| **Characters** | `O` | Everything the machine gave one character, least sure first. Fix the wrong ones, then confirm the rest with `Shift+Enter`. Below are lines it may have missed. |
| **Export** | `E` | Write the dataset. |

Once 10 lines of a character are confirmed and a few others are labeled "Other", the machine starts guessing. `Z` undoes the last step, `?` lists every key, and the Guide button explains the four views. The full guide is in [docs/USAGE.md](docs/USAGE.md).

## What you get

```text
exports/2026-10-24/
├── Teio/
│   ├── ep01_00083.120000_00085.430000.wav
│   └── ...
├── train.list      (GPT-SoVITS only: path|character|language|text)
└── rejected.tsv    (lines left out, and why)
```

Each clip is one line of one character: voice only, mono, at the sample rate of the video, with even loudness. Lines marked low quality are never exported. For GPT-SoVITS, a line is left out when its words in the spoken language cannot be found completely.

## Questions

**Can I use translated subtitles?** Yes. Lines are best cut from subtitles in the spoken language, but translated or bilingual ones work. But an episode cut from a translation can only be exported as sound (RVC and such), not with text for GPT-SoVITS. With a translation you read, give it as the secondary subtitles.

**It stopped halfway, for example out of graphics memory.** Add the same episode again. It continues where it stopped.

**Can I do it from the command line?** Yes: `uv run avoc add workspace "Episode 01.mkv" --subs "Episode 01.ja.srt"`. Run `uv run avoc --help` for all commands and options; the add form also shows the command for your workspace.

## Platforms

| Platform | Status |
| --- | --- |
| Windows 11 + NVIDIA graphics card | ✅ Tested (RTX 4060 Laptop) |
| Windows without a graphics card | Runs on the CPU, slower |
| Linux | ⚠️ Not tested yet. The install already picks the CUDA build of torch. |
| macOS | ⚠️ Not tested yet. CPU only. |

Reports from Linux and macOS are welcome in the issues.

## Docs

How it works, the words it uses, and what was tried and ruled out are in [docs/index.md](docs/index.md). To help, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Usage rules

The code is released under the [MIT License](LICENSE). The audio and text you extract with it belong to the rights holders of the original work. The MIT License does not cover them. By using this tool you agree:

- to use extracted material only for personal research or study;
- not to use extracted audio or text, or models trained on them, for any commercial purpose;
- not to use extracted voices to impersonate a character or voice actor.

## Acknowledgements

Built on [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), [anime-speaker-embedding](https://github.com/litagin02/anime_speaker_embedding), [ReDimNet](https://github.com/PalabraAI/redimnet2), [pyannote.audio](https://github.com/pyannote/pyannote-audio) and [pysubs2](https://github.com/tkarabela/pysubs2).
