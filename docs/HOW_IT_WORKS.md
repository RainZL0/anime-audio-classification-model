# Flow, data and terms

This page explains how things work. For how to type the commands, see [USAGE.md](USAGE.md). For why we chose this way, see [DECISIONS.md](DECISIONS.md). For the scoring rules, see [HISTORY.md](HISTORY.md#scoring).

| Section | What it covers |
| --- | --- |
| [Glossary](#glossary) | What each term in the docs means |
| [Five-step flow](#five-step-flow) | From one episode's audio track to audio sorted by character |
| [Labeling and correction interface](#labeling-and-correction-interface) | How the machine guesses, when it counts as confident, where labels are stored |
| [How scoring works](#how-scoring-works) | How linked pairs, wrong merges and missed merges are counted |
| [Data files](#data-files) | What each step writes, and where clip IDs come from |
| [Code layout](#code-layout) | Which file handles which part |

## Glossary

Some older notes used short words for these ideas. Those short words are retired. Use the terms below. If you meet one of them in an old commit message, check this table.

| Term | Meaning |
| --- | --- |
| Clip | The short piece of audio for one subtitle line. It is the smallest unit for labeling, grouping and scoring. |
| Offset | How many seconds the subtitle times differ from the audio track. For the same source and the same subtitle group, it stays almost the same. |
| Voiceprint | A set of numbers that describes a voice. It is used to check whether two clips may come from the same person. |
| Distance | The cosine distance between two voiceprints. 0 means the same direction exactly. A larger number means less alike. It is not "the chance that these are the same person". |
| Distance threshold | Two clips can be linked only if their distance is smaller than this value. The command-line option is `--threshold`. |
| Average linkage | A merge rule for hierarchical clustering: two groups merge only if the average distance between all their clips is within the threshold. On the command line it is called `average`. |
| Clip pool | The set of clips that are compared together in one grouping run. When three episodes are grouped together, the pool is all the clips of those three episodes. |
| Pool-relative threshold | The threshold is not fixed. It is computed from the pool's own distances: sort all pair distances from smallest to largest, take the distance at the 1% position, then multiply it by a fixed factor. On the command line it is `avs group --relative`. |
| Unassigned | A clip that is too short to have a voiceprint, so it does not take part in grouping. |
| Manual archive | The saved record of "clip to character name" that is made while labeling. It is stored in `annotations/`. |
| Retired old labels | `__multiple__` (more than one person), `__unclear__` (cannot tell), `__not_speech__` (not speech). They remain only in the blind-label archives in `annotations/` and in the old labeling page. The interface treats them as if the clip was never labeled. All of them were removed on 2026-10-23. |
| Same-character pairs / different-character pairs | Pairs made from clips that have a person's name, split by whether the two clips are the same character or not. |
| Linked | A same-character pair whose two clips were put in the same group. |
| Wrong merge | A different-character pair whose two clips were put in the same group. |
| Missed merge | A same-character pair whose two clips ended up in different groups. The audio is not lost; it just was not gathered together. |
| Linked share | Among the same-character pairs, the share that were linked. |
| Background clips | Clips that stay in the candidate pool as background. They are never asked about. |
| Ranking accuracy | Pick one same-character pair and one different-character pair at random. This is the share of times the same-character pair has the smaller distance. Pure chance gives 0.50. Perfect gives 1.00. |
| Equal error rate | Move the threshold to the point where the two kinds of error are equal: same-character clips kept apart, and different-character clips merged. This is the error rate at that point. Lower is better. |
| Held-out test | Scoring on data that took no part in tuning the settings. |
| Target character | A character the user wants to collect. Only target characters get names. Everyone else is labeled "Other". |
| Small classifier | A logistic regression trained on the manual labels, with voiceprints as input. There is one per target character. Its output is the probability that a clip is that target. |
| Confidence | The small classifier's probability for the top-ranked character. |
| Similarity check | Checks whether a clip is similar enough to the closest confirmed clip of the top-ranked character. If it is not, the speaker may be someone who has not been labeled yet. |
| Workspace | The folder that the interface opens. Inside it are `episodes/` (one folder per episode) and `labels/` (the labels made in the interface). |

## Five-step flow

**Video and subtitles → separate voices → cut clips along subtitle lines → compute voiceprints → group → label and score → export.**

In daily use, steps 3 to 5 are replaced by the [labeling and correction interface](#labeling-and-correction-interface). The grouping and scoring here are kept as a comparison experiment.

1. **`prepare`** (the first part of `add`): Takes the audio from the video (or from a separate audio file given with `--audio` on the same timeline). Separates the voices for the whole episode and keeps the original sample rate. Also makes a 16 kHz copy for analysis. Then adds this episode's offset to the subtitles, so **each subtitle line becomes one clip**. If `--offset` is not given, the offset is measured with speech detection. If the alignment is too weak, it stops with an error and does not quietly switch to another method.
2. **`embed`**: Computes a unit-length voiceprint for every clip that is at least 0.5 seconds long. Shorter clips stay in the clip table, but they have no voiceprint and cannot take part in grouping.
3. **`group`**: Puts the clips of all episodes into one pool and groups them directly by voiceprint. The defaults are `anime-va`, average linkage and a threshold of 0.70. Small groups are kept. They are not merged into one leftover group.
4. **`evaluate`**: Scores using only the manual archive. See the next section.
5. **`export`**: Cuts WAV files by group from the vocal track at the original sample rate. Clips with no group go to `_unassigned`. Loudness is evened out, but peaks are not clipped.

Helper commands: `coverage` checks whether any dialogue line in the subtitles was left out of the clips. `extend` adds such lines to the clip table. `label` opens the labeling page. `scores` only checks whether same-character and different-character pairs can be told apart, without grouping. `compare` sweeps the threshold. `drift` measures how the scores change as the pool gets bigger. `diagnose` runs nearest-neighbor search and looks at the distance spread.

"Only one person speaks in a clip" is a working assumption, not a detection result.

## Labeling and correction interface

`avs app` starts a web server that only listens on this machine. The front end has no build step. Its static files sit directly in `src/avs/app/static/`.

**Target characters and "Other".** The user names only the characters they want to collect. These are the target characters. Everyone else is labeled "Other", using the Q key. A workspace can have several target characters, and you can add or remove them while labeling:
- Each "Other" label records which target characters existed at that moment. It counts as "not this target" only for those characters.
- When you add a new target character, old "Other" labels do not count against it. Its Characters view has a section called "Maybe missed". It lists the clips that the machine did not assign to it but that have a fairly high probability of being it (this includes the old "Other" clips). The list starts with the most similar clips. They are labeled like any other clip.
- When you remove a target character, its labels stay as they are, and the machine stops guessing it. A clip that is the target cannot be any other target, so those labels are still used as negative examples. Adding the character back again loses nothing.
- New characters are target characters by default.
- "Low quality": in the interface this is one more choice. Each target character has two options, "target" and "target, low quality". "Other" has no such option, because it is never exported. When saving, "who it is" and "low quality" are stored separately. The name is still the target, and the two are decided together in every label. Choose "low quality" for clips with heavy background sound, overlapping voices, or anything else that does not belong in a clean dataset. These clips are not used for training and are skipped on export. They are not used as examples of the target, and they are not used as negatives either, because the target's voice really is in them. Earlier, "multiple people" was a separate switch. It was later merged into this choice, and old records count as "low quality". When several people speak and none of them is a target, label the clip "Other" directly.
- Only ask "is this the target?" If you are not sure, label it "Other". The old "unclear" and "multiple" labels are retired. The interface treats them as unlabeled.

**How the machine guesses.** The three voiceprint models (`anime-va`, `anime-char`, `redimnet2-b6`) are each scaled to unit length, joined together, and then scaled to unit length once more. For each target character, one logistic regression is trained with regularization strength 100:
- Positive examples are clips labeled as the target.
- Negative examples are clips labeled with another name, plus clips labeled "Other" while that target already existed. A wrong guess is simply corrected to the right person or to "Other". No separate "not the target" label is recorded.
- Clips labeled "low quality" are not used for training. We have not measured whether noisy clips help the machine find the target inside the noise, or whether they teach it the wrong thing. For now they are kept out.

The probability of "Other" is recorded as 1 minus the probability of the top target character. So the numbers do not always add up to 1. A training set has a few hundred to a few thousand clips. All target characters together take one or two seconds to train. So every label change retrains everything.

**When a clip counts as confident.** A clip skips the line-by-line check by a person only when both of these hold:

1. Its confidence is at least 0.6.
2. It passes the similarity check. The cutoff is measured from the confirmed clips of the target character. For each confirmed clip, take its highest similarity to the other confirmed clips of the same character. Then take the 5th percentile of those values. If there are fewer than 20 confirmed clips, no cutoff can be measured. In that case no clip counts as confident, and the interface does not show the "may be a voice not seen before" note. It only says that the machine can only pick among the characters it already knows. The similarity check is skipped when the top-ranked choice is "Other", because an unseen voice is labeled "Other" anyway.

The small classifier only picks among the characters it already knows, so the second condition is required. The numbers are in [EXPERIMENTS.md](EXPERIMENTS.md#confidence-in-the-interface).

**Starting groups.** Clips that have no label yet are grouped with `anime-va`, average linkage and a threshold of 0.70. A person then names each whole group.

**Text of a line.** A subtitle line counts as the text of a clip when their times overlap by at least half of the shorter of the two. Two clips that are more than 3 seconds apart start a new scene.

**Picture and sound.** ffmpeg cuts one clip at a time. The picture is 360p H.264 with 0.5 seconds of extra padding before and after. The sound is the same span of the vocal track. Both are cached in each episode's `app_media/`. Cutting one picture takes more than half a second. So when a person looks at a line, the server first cuts, in the background, the lines within 60 seconds before and after it in the same episode. Nearer lines go first, and the cutting then continues forward in time to the end of the episode. Two threads run in parallel. When the person moves to another line, the whole queue is replaced. Measured on episode 3: a line that was not cut in advance takes 0.8 to 1.1 seconds to open. A line cut in advance takes about 0.1 seconds. When the person presses L to hear More context, a separate copy with 5 or 15 seconds of extra time on each side is cut. Picture and sound start at the same moment. Their file names carry `.ctx5` or `.ctx15`. These are not cut in advance. The first time, they take about 0.6 and 1.1 seconds.

**Export.** Uses the same cutting as `export` (original sample rate, evened-out loudness). The formats are GPT-SoVITS `train.list` (each line is `path|character|language|text`), Style-Bert-VITS2 `esd.list`, or just one folder per character.

**Separate text subtitles.** When the subtitles used for the clips are a translation, you can attach a separate original-language subtitle file to each episode. On export, the text is taken from that file. The clips themselves do not change:

- When attaching, the offset is measured. The display times of both subtitle files are drawn as timelines with 10 ms cells. One is slid against the other, and the shift with the most overlap is taken. If the overlap is below 0.6, or fewer than 95% of the clips touch any dialogue, the attach is refused.
- When subtitles are read, the lines inside one entry are split apart, and the entry's time is shared among the lines by character count. A name at the start of a line becomes the speaker. Other sound notes in brackets are removed.
- For a clip, every line that overlaps it by more than 0.1 seconds must mostly fall inside the clip: 70% or more of it, or extending less than 0.8 seconds past each end. Together the lines must cover more than half of the clip. Only then is the text counted as complete.
- A character's name in the subtitles is the most common name among the named lines that overlap her clips. It must make up more than half of them. A line with a different name that overlaps a clip by more than 0.2 seconds marks that clip as mixed with someone else's speech. When the character's name cannot be found, two or more different names touching a clip also count as mixed.
- Clips whose text is incomplete, or that are mixed with someone else's speech, are not exported. They are written to `rejected.tsv` in the export folder, with the character, episode, start and end times, the reason, the original text and the attached text.

## How scoring works

- Only manual labels whose audio track matches, and whose start and end times match to the millisecond, take part.
- The total number of **same-character pairs**: if a character has n clips with names, there are n(n−1)/2 pairs for that character. Add up all the characters. It is not the number of combinations of all labels without splitting by character.
- Example: a character has clips A, B and C. A and B are in the same group, and C is in its own group. There are 3 same-character pairs in total. 1 is linked. 2 are missed merges.
- Each unassigned clip counts as its own separate group in scoring. A clip without a person's name cannot be treated as "no other character got mixed in".
- The report also lists the labels that did not match, the unassigned clips, and how many groups each character is spread across. The `adjusted_rand` in it is an overall score. It does not replace the two concrete counts, wrong merges and missed merges.

## Data files

Each episode has a folder `runs/episodes/<episode>/`:

- `episode.json` records the paths of the source and the audio tracks. `segments.json` records the clip IDs, the episode name, and the start and end times. For an episode with attached text subtitles, `episode.json` also has `text_subtitles` (the path), `text_subtitle_offset` (the offset in seconds) and `text_subtitle_agreement` (the overlap).
- Voiceprints are stored in `embeddings/<model name>/`. Those made with a different minimum clip length are stored in `embeddings/<model name>@w<seconds>/`. The matrix and its metadata line up row by row. The cache is tied to the content of the clip files, the content of the analysis audio, the model name and the minimum length. If any of these changes, the cache must be recomputed. An old cache raises an error. It is never used silently.
- `label_audio/<archive name>/` holds the audio and video that the labeling page cuts on demand. `app_media/` holds what the interface cuts.

The interface's labels are stored in the workspace folder `labels/`:

- `events.jsonl` is append-only. Each line is one batch of changes, and it records each clip's value before and after the change. An undo is also a batch, and it records which batch it undoes. Imported batches cannot be undone. The cast table `cast.json` is stored separately. When a batch also creates, renames or merges characters, the batch's `cast` field records it, and an undo restores the cast table as well. A new character that has no clips left after an undo is deleted. Replaying all the lines gives the current labels.
- `cast.json` is the cast table. It holds the name, whether a person gave the name (`named`), the color, the pattern number (`pattern`), the avatar file, and whether the character takes part in training. A character without a name is shown as "Character N". Giving it a name is a rename. Pattern numbers only grow and are never reused. When no avatar has been cropped, the default picture is drawn from the pattern number. Avatar images are stored in the `avatars/` folder next to it.

These labels are kept apart from the manual archives under `annotations/`. The reason is in [HISTORY.md](HISTORY.md#labeling).

**Clip IDs are a hash of the episode name plus the start and end times. They do not depend on neighboring clips.** So adding rows to the clip table without changing existing rows keeps the existing labels. Re-cutting makes all labels invalid.

The grouping file `groups.json` stores each episode's audio track position and each clip's group. `speaker=null` means the clip is unassigned. The paths are absolute, so moving the project means updating the audio track positions. Clip IDs do not change when folders are moved or when the clips are regrouped.

For the format of the manual archives, see [annotations/README.md](../annotations/README.md).

## Code layout

```text
src/avs/
  cli.py                   command entry point
  project.py               data format for an episode and its clips, content fingerprints, cache folders
  pipeline.py              orchestration of prepare, extending clips, voiceprint cache, grouping, export
  audio.py                 voice separation, making the analysis copy, the speech timeline used to measure subtitle offset
  embeddings/extract.py    four voiceprint models and the minimum clip length
  stages/subtitle.py       read subtitles, measure offset
  stages/text_subtitle.py  attached text subtitles: split lines, measure offset, give clips their text
  stages/cluster.py        global voiceprint grouping and several merge rules
  stages/normalize.py      score normalization (shown to be ineffective, kept as evidence)
  stages/export.py         export at the original sample rate
  evaluation/identity.py   identity scoring
  evaluation/compare.py    sweep models and thresholds on the same clips and labels
  evaluation/drift.py      measure how scores change as the pool grows, compare two ways of setting the threshold
  evaluation/coverage.py   dialogue coverage check, cut the lines that were not covered
  evaluation/scores.py     ranking accuracy and equal error rate, split by length and across episodes
  evaluation/references.py a few identity reference experiments (closed, kept as evidence)
  evaluation/diagnose.py   nearest-neighbor search, distance distribution, error cases
  evaluation/classify.py   hold out by episode, compare several ways of assigning clips to character names
  labeling.py              plan the labeling range, cut audio and video, save manual archives
  label_page.py            old labeling page for blind labeling
  app/workspace.py         read the workspace: episodes, clips, text, scenes, assembled voiceprints
  app/labels.py            label records in the interface, undo, cast table, importing old archives
  app/model.py             small classifier and similarity check
  app/server.py            web server endpoints, picture cutting, export
  app/static/              front-end pages
```
