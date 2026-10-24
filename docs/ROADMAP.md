# Roadmap

This page covers who the tool is for, the direction it takes, and what is planned next. Settled choices are in [DECISIONS.md](DECISIONS.md). How things work now is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Who it is for

- Mainly, people who want to train a voice model for one character (GPT-SoVITS, RVC and so on), and who need clean audio of that character speaking alone, with the line in the language spoken.
- Second, people who want to find all of a character's lines.

## Direction

The current approach (cut along subtitle lines, name a few lines, let a small classifier sort the rest and retrain after every correction) is settled in [DECISIONS.md](DECISIONS.md#settled). Beyond it:

- Use the order of neighboring lines, the subtitle text, and the lip movement in the picture to tell people apart.
- Once labels reach several thousand, consider fine-tuning the voiceprint model. At that point, the "do not fine-tune the models" item in [DECISIONS.md](DECISIONS.md#settled) must be changed first.

## Labeling interface

The first version is done, with four views: Groups, Scenes, Characters and Export. How to use each view and its shortcuts are in [USAGE.md](USAGE.md#labeling-and-correction-interface). How the machine guesses and where the labels are stored is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface). The design rules that must be kept are in [UI_DESIGN.md](UI_DESIGN.md).

Planned:

- **Show which lines are low quality.** Train another classifier, inside the clips of a target character, that separates "clean" from "low quality" (heavy background sound, several people speaking at once). It would hint that the person should choose "low quality". It only answers whether a clip can go into a clean dataset, not who is speaking. So low-quality clips count as negatives here, but they still do not count as negatives in the classifier that identifies people. As the number of lines grows, choosing this by hand is a large share of the labeling work, which is why it is worth doing. Its accuracy has been measured on Teio's labels, and it is good enough to build. The voiceprints separate clean clips from noisy ones only partly. A general speech model does clearly better, so the hint uses it ([DECISIONS.md](DECISIONS.md#settled)).

## Platforms

Only Windows has been tested. Linux and macOS already have first support in the install setup ([TOOLS.md](TOOLS.md)), and testing them is planned. A one-click Windows package may come later.
