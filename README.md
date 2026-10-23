# anime-voice-collector

Collect every line a chosen anime character speaks, as clean single-speaker audio clips with their text, ready for training GPT-SoVITS, Style-Bert-VITS2 or RVC.

You give it each episode's video and subtitles. It cuts the dialogue into clips along the subtitle lines and separates the voices from the music and effects. Then you label a few clips while watching the scene, and a small model learns to recognize your character. When you correct one of its mistakes, it retrains in a few seconds and its other guesses update right away. When you are done, export the character's clips.

## What you need

- [uv](https://docs.astral.sh/uv/) (it installs the right Python for you)
- [FFmpeg](https://ffmpeg.org/) on your `PATH` (both `ffmpeg` and `ffprobe`)
- An NVIDIA GPU is strongly recommended. Without one everything runs on the CPU, but separating the voices of one episode takes much longer.
- For each episode: the video, and a subtitle file (`.ass` or `.srt`) whose lines match the dialogue. The subtitles can be a translation. For a Japanese voice model, you can attach a separate Japanese subtitle file and the exported text comes from it.

Tested on Windows 11 with an RTX 4060 Laptop GPU. Linux should work but has not been tried yet. macOS can only use the CPU and has not been tried either.

## Quick start

```bash
git clone https://github.com/RainZL0/anime-voice-collector.git
cd anime-voice-collector
uv sync --locked
uv run avoc doctor
```

`doctor` checks the GPU, FFmpeg, the voice separation model, your Hugging Face token and free disk space. Fix anything it marks as missing.

Add an episode to a workspace folder, here `workspace` inside the project folder (git ignores it). Any other folder works too. One command separates the voices, cuts the clips and computes everything the labeling app needs:

```bash
uv run avoc add workspace "Episode 01.mkv" --subs "Episode 01.ass" --offset 0
```

- `--offset` is how many seconds to add to the subtitle times so they line up with the audio. Episodes from the same video source and the same subtitle group almost always share one offset. Find it once, then reuse it.
- If you leave out `--offset`, the tool measures it with [pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1). That model is gated: accept its terms on Hugging Face, then run `uv run hf auth login`.
- `--text-subs "Episode 01.ja.ass"` attaches a second subtitle file. The exported text is taken from it, which is useful when the first one is a translation.
- If a run stops halfway (out of GPU memory, for example), run the same command again. It continues where it stopped.

Open the labeling app:

```bash
uv run avoc app workspace
```

It opens `http://127.0.0.1:8765` in your browser. Everything stays on your machine.

## How labeling works

You only name the characters you want (the targets). Everyone else gets a single label, "other". You can add or remove targets at any time, and existing labels stay valid.

- **Groups (G):** start here. Clips that sound alike are grouped, so you can label a whole group at once.
- **Scenes (S):** every line in order, with the video playing. Press Enter to accept the model's guess, a number key to pick a target, Q for "other", and Shift + number to mark a target's clip as low quality (background noise, overlapping voices). Low-quality clips are never used for training and are skipped on export.
- **Characters (O):** everything the model assigned to one character, least confident first. Fix the wrong ones, then confirm the rest with Shift+Enter. Below that is a list of clips the model may have missed.
- **Export (E):** GPT-SoVITS list files, Style-Bert-VITS2, or one folder per character. Clips are cut from the separated vocals at the original sample rate.

Z undoes the last step. Run `uv run avoc --help` to list all commands.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Usage rules

The code is released under the [MIT License](LICENSE). The audio and text you extract with it belong to the rights holders of the original work. The MIT License does not cover them. By using this tool you agree:

- to use extracted material only for personal research or study;
- not to use extracted audio or text, or models trained on them, for any commercial purpose;
- not to use extracted voices to impersonate a character or voice actor, or to make content that could be mistaken for their own;
- not to distribute extracted audio publicly.
