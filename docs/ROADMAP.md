# Roadmap

This page covers who the tool is for, the direction it takes, and what is planned next. Settled choices are in [DECISIONS.md](DECISIONS.md). How things work now is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Who it is for

- Mainly, people who want to train a voice model for one character (GPT-SoVITS, Style-Bert-VITS2, RVC and so on), and who need clean audio of that character speaking alone, with the line in the language spoken.
- Second, people who want to find all of a character's lines.

## Direction

- **Input**: each episode must have both video and subtitles. If either is missing, processing is refused. The subtitles decide how to cut the clips, and the video lets the labeler identify people.
- **Identifying people**: the voiceprint models stay as they are. A small classifier is trained on the manual labels, and it assigns clips directly to character names. The small classifier trains in a few seconds, so it can be retrained right away after every label change. Each prediction comes with a confidence. Confident predictions are accepted directly. Low-confidence ones go to "needs review". Clips that resemble nobody are marked as unknown or as a new character.
- **Why it beats grouping**: grouping compares one clip with another clip, and both are noisy. It also relies on one global threshold, which drifts as more episodes are added. Classification compares one clip with dozens of clips of one character, and each character has its own boundary.
- **Start**: use the existing groups (few wrong merges, but split into many small pieces) so that a person can name each whole group. A batch of clips is labeled in one go.
- **Later**: use the order of neighboring lines, the subtitle text, and the lip movement in the picture. Once labels reach several thousand, consider fine-tuning the voiceprint model. At that point, the "do not fine-tune the models" item in [DECISIONS.md](DECISIONS.md#settled) must be changed first.

## Labeling interface

The first version is done, with four views: Groups, Scenes, Characters and Export. How to use each view and its shortcuts are in [USAGE.md](USAGE.md#labeling-and-correction-interface). How the machine guesses and where the labels are stored is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface). The design rules that must be kept are in [UI_DESIGN.md](UI_DESIGN.md).

Planned:

- **Show which lines are low quality.** Train another classifier, inside the clips of a target character, that separates "clean" from "low quality" (heavy background sound, several people speaking at once). It would hint that the person should choose "low quality". It only answers whether a clip can go into a clean dataset, not who is speaking. So low-quality clips count as negatives here, but they still do not count as negatives in the classifier that identifies people. As the number of lines grows, choosing this by hand is a large share of the labeling work, which is why it is worth doing. Its accuracy has been measured on Teio's labels, and it is good enough to build. The voiceprints separate clean clips from noisy ones only partly. A general speech model does clearly better, so the hint uses it ([DECISIONS.md](DECISIONS.md#settled)).

## Platforms

Only Windows has been tested. Linux and macOS already have first support in the install setup ([TOOLS.md](TOOLS.md)), and testing them is planned. A one-click Windows package may come later.
