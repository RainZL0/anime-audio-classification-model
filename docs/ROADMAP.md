# Roadmap to the first release

Updated: 2026-10-24. This page covers the goals, the direction and the standards up to the first release. The next steps for now are in [STATUS.md](STATUS.md). The direction has been settled ([DECISIONS.md](DECISIONS.md#settled)). The labeling interface has a first version. [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface) explains how it works.

## Goal

- Make a tool that is worth publishing publicly. The target is 1000 stars on GitHub.
- Main users: people who want to train a voice model for one character (GPT-SoVITS, Style-Bert-VITS2, RVC and so on), and who need clean audio of that character speaking alone. Second, people who want to find all of a character's lines.
- Almost no similar tool has a step where the model gets better after you correct its mistakes. See [COMPETITORS.md](COMPETITORS.md#5-gaps-we-can-own).

## Repo

- The first release is developed locally in this repo. Nothing more is pushed before release. An early `feat/voice-sorter-v1` branch from 2026-10-18 is already on GitHub. Delete it at release.
- At release, force-push this repo's history onto the `main` branch of the old GitHub repo `RainZL0/anime-audio-classification-model`, replacing it. The old repo is kept so that its existing stars and links are kept. The old `main` is kept as the tag `archive/old-main`, which is already pushed. At the same time, rename the repo to `anime-voice-collector` (decided 2026-10-24); GitHub redirects the old address to the new one. The command is `avoc`, short for anime voice collector. `avc` was not used because it is also the name of the H.264 video format, which shows up in anime file names.

## Direction

- **Input**: each episode must have both video and subtitles. If either is missing, processing is refused. The subtitles decide how to cut the clips, and the video lets the labeler identify people.
- **Identifying people**: the voiceprint models stay as they are. A small classifier is trained on the manual labels, and it assigns clips directly to character names. The small classifier trains in a few seconds, so it can be retrained right away after every label change. Each prediction comes with a confidence. Confident predictions are accepted directly. Low-confidence ones go to "needs review". Clips that resemble nobody are marked as unknown or as a new character.
- **Why it beats grouping**: grouping compares one clip with another clip, and both are noisy. It also relies on one global threshold, which drifts as more episodes are added. Classification compares one clip with dozens of clips of one character, and each character has its own boundary.
- **Start**: use the existing groups (few wrong merges, but split into many small pieces) so that a person can name each whole group. A batch of clips is labeled in one go.
- **Later**: use the order of neighboring lines, the subtitle text, and the lip movement in the picture. Once labels reach several thousand, consider fine-tuning the voiceprint model. At that point, the "do not fine-tune the models" item in [DECISIONS.md](DECISIONS.md#settled) must be changed first.

## Labeling interface

The first version is done, with four views: Groups, Scenes, Characters and Export. How to use each view and its shortcuts are in [USAGE.md](USAGE.md#labeling-and-correction-interface). How the machine guesses and where the labels are stored is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface). The design rules that must be kept are in [UI_DESIGN.md](UI_DESIGN.md).

Not done yet:

- Error messages for when something goes wrong still need a pass by a first-time user. Done: the first-use welcome page with machine checks, and adding an episode from inside the interface, with progress, stop and carry on ([USAGE.md](USAGE.md#labeling-and-correction-interface)).
- **Show which lines are low quality.** Train another classifier, inside the clips of a target character, that separates "clean" from "low quality" (heavy background sound, several people speaking at once). It would hint that the person should choose "low quality". It only answers whether a clip can go into a clean dataset, not who is speaking. So low-quality clips count as negatives here, but they still do not count as negatives in the classifier that identifies people. There are now enough labels to start: on 2026-10-24, 155 of the 615 clips labeled as a target character were "low quality". As the number of lines grows, choosing this by hand is a large share of the labeling work, which is why it is worth doing. First measure how accurate it is. The voiceprint models were trained to recognize people regardless of noise, so they may not be able to separate clean clips from noisy ones. If so, a different feature is needed. The "spread of voiceprints across several windows within a clip" that was tried earlier is described in [TOOLS.md](TOOLS.md).

## First release standard

The first item used to be "prove with numbers that classification is clearly better than grouping". It was removed on 2026-10-23. In real labeling, classification feels much better, so no separate comparison is made for the release ([DECISIONS.md](DECISIONS.md#settled)).

1. **Labeling interface**: naming whole groups, two views of the same clips (Scenes and Characters), keyboard use, undo, and immediate retraining after each edit. The first version is done and is still being polished.
2. **Export**: at least the GPT-SoVITS list format, with the dialogue text. GPT-SoVITS, Style-Bert-VITS2 and one folder per character are already supported, with the text taken from the subtitles (format in [COMPETITORS.md](COMPETITORS.md#2-dataset-format-expected-by-training)). When the subtitles used for cutting are translations, each episode can have a separate Japanese subtitle file for the text. No speech-to-text is needed.
3. **Install**: `uv sync` installs everything in one command, and adding an episode takes one `avoc add`. Only Windows is supported for the first release. Linux and macOS have first support in the install setup ([TOOLS.md](TOOLS.md)) but have not been tested; the README lists them as untested, and testing them comes after the first release. A one-click Windows package can come after the first release too.
4. **README**: a demo GIF at the top, and one sentence saying what the tool is for, laid out like popular open-source repos (centered title, badges, short feature list, then quick start). The README is English only, so the pushed repo has no Chinese README. The English version is written. The GIF is still missing. The license is settled: MIT for the code.
5. **No pictures or videos in git.** Screenshots and GIFs for the README and docs are uploaded as attachments to one GitHub issue, and the Markdown links to their addresses there. This keeps the repo small for `git clone`. The scope of use for the extracted material is written in the "Usage rules" section of the README. The MIT license itself allows commercial use, so the "no commercial use" rule applies to the extracted material, not to the code.

## Release

- Release in two steps. First, push the first version to `main` once the standards above are met (the repo steps are under [Repo](#repo)). No trial users are sought before this (decided 2026-10-24). Later, announce it on the same day on Bilibili, Zhihu, V2EX, Reddit, Hacker News and X.
- In Japan, permission to use voice actors' voices is a sensitive topic. The README states the limits of use clearly. The promotion focuses on organizing and searching the lines.
