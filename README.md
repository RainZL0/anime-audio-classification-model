<div align="center">

# anime-voice-collector

**Collect every line one anime character speaks, as clean clips with their text, ready for voice training.**

[![CI](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml/badge.svg)](https://github.com/RainZL0/anime-voice-collector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg?logo=windows&logoColor=white)](#platforms)

[Quick start](#quick-start) · [How labeling works](#how-labeling-works) · [Export formats](#export-formats) · [Docs](docs/index.md) · [Contributing](CONTRIBUTING.md)

<!-- Demo GIF: upload it to the media issue, then put its address here. No pictures are kept in git. -->

</div>

## Why

To train a voice model of one character (GPT-SoVITS, Style-Bert-VITS2, RVC), you need minutes of that character speaking alone, each clip with its line. Doing it by hand means scrubbing through every episode. Most tools stop at grouping voices that sound alike and leave the rest to you.

Here you label a few clips while watching the scene. A small model learns your character, sorts the rest, and **retrains in a few seconds every time you correct it**, so its other guesses update right away.

## Features

- 🎬 **Cut by subtitles.** Each dialogue line becomes one clip, so no line is lost to a speech detector.
- 🎤 **Voices separated** from music and effects for every clip.
- 🧠 **Learns from your corrections.** Label a target character and "other"; the model updates as you go.
- 📺 **Label while watching.** The video plays with each line, with more context one key away.
- ⌨️ **Keyboard first,** with undo.
- 🈶 **Text in the language spoken.** Cut with translated or bilingual subtitles; the exported text is always the words actually said, and each clip shows it while you label.
- 📦 **Export** to GPT-SoVITS, Style-Bert-VITS2, or one folder per character, at the original sample rate.
- 🔒 **Runs on your machine.** Nothing is uploaded.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (it installs the right Python for you) and [FFmpeg](https://ffmpeg.org/) on your `PATH` (`ffmpeg` and `ffprobe`). An NVIDIA GPU is strongly recommended; without one, separating the voices of one episode takes much longer.

```bash
git clone https://github.com/RainZL0/anime-voice-collector.git
cd anime-voice-collector
uv sync --locked
uv run avoc doctor
```

`doctor` checks the GPU, FFmpeg, the voice separation model, your Hugging Face token and free disk space. Fix anything it marks as missing.

**1. Add an episode** to a workspace folder. You need its video and a subtitle file (`.ass` or `.srt`) whose lines match the dialogue, best in the language spoken. One command separates the voices, cuts the clips and computes everything the labeling app needs:

```bash
uv run avoc add workspace "Episode 01.mkv" --subs "Episode 01.ja.srt" --offset 0
```

| Option | What it does |
| --- | --- |
| `--offset` | Seconds to add to the subtitle times so they line up with the audio. Episodes from the same video source and subtitle group almost always share one offset: find it once, then reuse it. |
| *(no `--offset`)* | The offset is measured with [pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1). That model is gated: accept its terms on Hugging Face, then run `uv run hf auth login`. |
| `--display-subs "Episode 01.zh.ass"` | A translation you can read, shown above each line while labeling. Nothing is exported from it. |
| `--text-subs "Episode 01.ja.ass"` | Only when `--subs` is a translation: attach subtitles in the language spoken, and the exported text is taken from them. Many clips get no text this way, so prefer `--subs` in the spoken language. |
| `--spoken ja` | The language spoken (`ja`, `zh`, `en`, `ko`). By default it is read from the audio track, and the matching track of a dual-audio video is used. |

If a run stops halfway (out of GPU memory, for example), run the same command again. It continues where it stopped. You can also add episodes from inside the app.

**2. Open the labeling app:**

```bash
uv run avoc app workspace
```

It opens `http://127.0.0.1:8765` in your browser.

## How labeling works

You only name the characters you want (the targets). Everyone else gets a single label, "other". You can add or remove targets at any time, and existing labels stay valid.

| View | Key | What you do there |
| --- | :---: | --- |
| **Groups** | `G` | Start here. Clips that sound alike are grouped, so you can label a whole group at once. |
| **Scenes** | `S` | Every line in order, with the video playing. `Enter` accepts the model's guess, a number picks a target, `Q` means "other", `Shift` + number marks a target's clip as low quality (background noise, overlapping voices). |
| **Characters** | `O` | Everything the model gave one character, least confident first. Fix the wrong ones, then confirm the rest with `Shift+Enter`. Below it are clips the model may have missed. |
| **Export** | `E` | Write the dataset. |

`Z` undoes the last step. Low-quality clips are never used for training and are skipped on export. Run `uv run avoc --help` to list all commands; the full guide is in [docs/USAGE.md](docs/USAGE.md).

## Export formats

| Format | Output |
| --- | --- |
| GPT-SoVITS | Clips and `train.list` with each line's text |
| Style-Bert-VITS2 | Clips and `esd.list` with each line's text |
| One folder per character | Plain audio clips |

Clips are cut from the separated vocals at the original sample rate. The text is in the language spoken. Clips whose text cannot be matched completely are left out and listed in `rejected.tsv`.

## Platforms

| Platform | Status |
| --- | --- |
| Windows 11 + NVIDIA GPU | ✅ Tested (RTX 4060 Laptop) |
| Windows without a GPU | Runs on the CPU, slower |
| Linux | ⚠️ Not tested yet. The install already picks the CUDA build of torch. |
| macOS | ⚠️ Not tested yet. CPU only. |

Reports from Linux and macOS are welcome in the issues.

## Docs

How it works, the terms it uses, and what was tried and ruled out are in [docs/index.md](docs/index.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Usage rules

The code is released under the [MIT License](LICENSE). The audio and text you extract with it belong to the rights holders of the original work. The MIT License does not cover them. By using this tool you agree:

- to use extracted material only for personal research or study;
- not to use extracted audio or text, or models trained on them, for any commercial purpose;
- not to use extracted voices to impersonate a character or voice actor.

## Acknowledgements

Built on [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), [anime-speaker-embedding](https://github.com/litagin02/anime_speaker_embedding), [ReDimNet](https://github.com/PalabraAI/redimnet2), [pyannote.audio](https://github.com/pyannote/pyannote-audio) and [pysubs2](https://github.com/tkarabela/pysubs2).
