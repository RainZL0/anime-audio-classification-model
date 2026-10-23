# Dependencies, models and runtime environment

The actual versions are in `pyproject.toml` and `uv.lock`. Which model was chosen, and why, is in [DECISIONS.md](DECISIONS.md). This page only says what each tool is and how it is connected.

## Audio processing

- **FFmpeg**: makes the 16 kHz analysis copy. The interface cuts video pictures on demand and converts them to 360p H.264. The vocals at the original sample rate are kept for export.
- **audio-separator / Mel-Band RoFormer**: separates the vocals. Model file `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`. The default is fp16. Measured on the same 3-minute clip on an RTX 4060 Laptop, fp16 is about 1.6 times faster than fp32. Its output differs from fp32's by a signal-to-noise ratio of 73.5 dB, which means the difference is far below what you can hear. bf16 is slower, and its output differs from fp32 by only 15.6 dB, so it is not chosen. Measure again when the GPU architecture changes. If you suspect separation artifacts, use `--precision fp32` to compare. `audioread` is a dependency that the package does not declare but that is actually needed. It is kept.
- **pyannote community-1**: used only to measure the subtitle offset when `--offset` is not given. The WeSpeaker adapter also depends on it. It reads from the waveform tensor, which avoids a problem with the FFmpeg DLL used by torchcodec on Windows.
- soundfile, pyloudnorm: read the tracks at the original sample rate and handle loudness. pysubs2, Typer: subtitles and the command line. scikit-learn: the starting groups and the small classifier in the interface.

## Voiceprint models

| Command-line name | Source | Status |
| --- | --- | --- |
| `anime-va` | [anime_speaker_embedding](https://github.com/litagin02/anime_speaker_embedding) variant trained by voice actor (989 voice actors) | Default for grouping. One of the three joined together in the interface |
| `anime-char` | Same project, variant trained by character (7357 characters) | One of the three joined together in the interface |
| `redimnet2-b6` | [ReDimNet2](https://github.com/PalabraAI/redimnet2), the default variant, trained only on VoxCeleb2 | One of the three joined together in the interface. It was the default for grouping before 2026-09-07 |
| `wespeaker-resnet293` | [WeSpeaker ResNet293](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet293-LM) | Ruled out. Runs on the CPU on Windows |

- **anime_speaker_embedding**: ECAPA-TDNN with BatchNorm replaced by GroupNorm, trained on about 7 million audio clips from visual novels. MIT license, 192 dimensions, input is 16 kHz mono. The package's `get_embedding` only accepts file paths. We bypass it and feed arrays directly, so that a temporary file does not have to be written for every clip.
- **ReDimNet2**: loaded through torch.hub, using the official code and model. The official project also has two variants, `vb2+vox2` and `vb2+vox2+cnc2`, which do better across datasets. They have not been tried. The remote code of torch.hub is not in the lock file. After the model or the remote code is upgraded, the old thresholds and caches must not be compared again without checking them first.
- Similarity scales differ between models, so each model's threshold is swept separately. See [DECISIONS.md](DECISIONS.md#settled).

## Interface

- **FastAPI + uvicorn**: the web server for `avoc app`. It listens only on 127.0.0.1.
- **Preact + htm**: the front end. It uses the single-file build of htm 3.1.1 (`src/avoc/app/static/vendor/preact-htm.js`, Apache-2.0; the license is in the same folder). No Node and no build tool are needed.
- The tests drive the FastAPI test client through httpx.

## Runtime environment

On Windows and Linux, torch and torchaudio are both installed as CUDA 12.8 wheels. Without an NVIDIA GPU, the same wheels run on the CPU. macOS uses the default wheels from PyPI and can only run on the CPU. The lock file makes this choice. CI also installs the CUDA wheels on Linux. The downloaded wheels are saved in the cache (`prune-cache: false`), so they do not have to be downloaded again each time. Only Windows with an RTX 4060 has been tested so far. Linux and macOS have not been tried yet.

## Leads for later

These are only entry points left over from older research. They are not verified choices, and they are not the current plan. Check each one again before using it.

- [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet): noise reduction.
- [ClearerVoice-Studio](https://github.com/modelscope/ClearerVoice-Studio): speech enhancement and separation.
- [VoiceFilter](https://google.github.io/speaker-id/publications/VoiceFilter/): extracts only the voice of a given speaker.
- The spread of voiceprints from several windows within one clip (formerly named `selfsim_spread`): detects whether a second person is mixed into a clip. It was tried once against a control matched for clip length, using 34 manual labels from episode 1. There was a signal, but the sample was too small to conclude anything. The code has been deleted. When multi-person clips are handled later, it must be implemented again and checked with new labels.
- voxmap-studio (2026, open source): an off-the-shelf interface for manually editing groups. It supports splitting, merging, reassigning, and unifying numbers across files. Only the paper has been read. No code was found, and it has not been tried.
