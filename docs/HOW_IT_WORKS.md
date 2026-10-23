# Flow, data and terms

This page explains how things work. For how to type the commands, see [USAGE.md](USAGE.md). For why we chose this way, see [DECISIONS.md](DECISIONS.md).

| Section | What it covers |
| --- | --- |
| [Glossary](#glossary) | What each term in the docs means |
| [Flow](#flow) | From one episode's video and subtitles to clips ready for labeling |
| [Labeling and correction interface](#labeling-and-correction-interface) | How the machine guesses, when it counts as confident, where labels are stored |
| [Data files](#data-files) | What each step writes, and where clip IDs come from |
| [Code layout](#code-layout) | Which file handles which part |

## Glossary

| Term | Meaning |
| --- | --- |
| Clip | The short piece of audio for one subtitle line. It is the smallest unit for labeling. |
| Offset | How many seconds the subtitle times differ from the audio track. For the same source and the same subtitle group, it stays almost the same. |
| Style | In an ASS subtitle file, every line belongs to a named style, such as "Default" or "OP", which sets its font and place on screen. Subtitle groups often put dialogue, song lyrics and on-screen text in different styles. SRT files have no styles, so all their lines count as one style, "Default". |
| Voiceprint | A set of numbers that describes a voice. It is used to check whether two clips may come from the same person. |
| Distance | The cosine distance between two voiceprints. 0 means the same direction exactly. A larger number means less alike. It is not "the chance that these are the same person". |
| Distance threshold | In the Groups view, two groups merge only if their distance is smaller than this value. |
| Average linkage | A merge rule for hierarchical clustering: two groups merge only if the average distance between all their clips is within the threshold. |
| Too short for a voiceprint | A clip shorter than 0.5 seconds. It stays in the clip table, but it has no voiceprint, so the machine makes no guess for it. |
| Target character | A character the user wants to collect. Only target characters get names. Everyone else is labeled "Other". |
| Small classifier | A logistic regression trained on the manual labels, with voiceprints as input. There is one per target character. Its output is the probability that a clip is that target. |
| Confidence | The small classifier's probability for the top-ranked character. |
| Similarity check | Checks whether a clip is similar enough to the closest confirmed clip of the top-ranked character. If it is not, the speaker may be someone who has not been labeled yet. |
| Workspace | The folder that the interface opens. Inside it are `episodes/` (one folder per episode) and `labels/` (the labels made in the interface). |

## Flow

**Video and subtitles → separate voices → cut clips along subtitle lines → compute voiceprints → label and correct in the interface → export.**

`add` does the first steps in one command:

1. **Reading the subtitles**: The file is read whatever its text encoding: UTF-8 and UTF-16 directly, and older Chinese, Japanese, Korean and Western encodings by trying each and keeping the reading that looks most like real text. ASS, SRT, WebVTT and a few rarer formats are told apart by their content, not by the file extension. Then the dialogue [styles](#glossary) are picked: the main one is the style with the most lines among those whose lines appear across the whole episode (an opening song has many lines, but all at the start). Styles named after it, such as "Default - Top", and other spread-out styles with at least a quarter as many lines (the second language of bilingual subtitles) are dialogue too. Comment lines, vector drawings and lines over 20 seconds are dropped. `add` prints which styles it used and which it left out, `avoc styles <file>` shows each style with sample lines, and `--styles` overrides the choice.
2. **`prepare`**: Takes the audio from the video (or from a separate audio file given with `--audio` on the same timeline). Separates the voices for the whole episode and keeps the original sample rate. Also makes a 16 kHz copy for analysis. Then adds this episode's offset to the subtitles, so **each subtitle line becomes one clip**. If `--offset` is not given, the offset is measured with speech detection. If the alignment is too weak, it stops with an error and does not quietly switch to another method.
3. **`embed`**: Computes a unit-length voiceprint for every clip that is at least 0.5 seconds long, once for each of the three models the interface uses. Shorter clips stay in the clip table, but they have no voiceprint.

Labeling and export then happen in the [interface](#labeling-and-correction-interface).

"Only one person speaks in a clip" is a working assumption, not a detection result.

## Labeling and correction interface

`avoc app` starts a web server that only listens on this machine. The front end's source is in `web/`. The server sends the built files in `src/avoc/app/static/`, which are committed, so running the app needs no Node. How to change the front end is in [CONTRIBUTING.md](../CONTRIBUTING.md).

**Target characters and "Other".** The user names only the characters they want to collect. These are the target characters. Everyone else is labeled "Other", using the Q key. A workspace can have several target characters, and you can add or remove them while labeling:
- Each "Other" label records which target characters existed at that moment. It counts as "not this target" only for those characters.
- When you add a new target character, old "Other" labels do not count against it. Its Characters view has a section called "Maybe missed". It lists the clips that the machine did not assign to it but that have a fairly high probability of being it (this includes the old "Other" clips). The list starts with the most similar clips. They are labeled like any other clip.
- When you remove a target character, its labels stay as they are, and the machine stops guessing it. A clip that is the target cannot be any other target, so those labels are still used as negative examples. Adding the character back again loses nothing.
- New characters are target characters by default.
- "Low quality": in the interface this is one more choice. Each target character has two options, "target" and "target, low quality". "Other" has no such option, because it is never exported. When saving, "who it is" and "low quality" are stored separately. The name is still the target, and the two are decided together in every label. Choose "low quality" for clips with heavy background sound, overlapping voices, or anything else that does not belong in a clean dataset. These clips are not used for training and are skipped on export. They are not used as examples of the target, and they are not used as negatives either, because the target's voice really is in them. When several people speak and none of them is a target, label the clip "Other" directly.
- Only ask "is this the target?" If you are not sure, label it "Other".

**How the machine guesses.** The three voiceprint models (`anime-va`, `anime-char`, `redimnet2-b6`) are each scaled to unit length, joined together, and then scaled to unit length once more. For each target character, one logistic regression is trained with regularization strength 100:
- Positive examples are clips labeled as the target.
- Negative examples are clips labeled with another name, plus clips labeled "Other" while that target already existed. A wrong guess is simply corrected to the right person or to "Other". No separate "not the target" label is recorded.
- Clips labeled "low quality" are not used for training. We have not measured whether noisy clips help the machine find the target inside the noise, or whether they teach it the wrong thing. For now they are kept out.

The probability of "Other" is recorded as 1 minus the probability of the top target character. So the numbers do not always add up to 1. A training set has a few hundred to a few thousand clips. All target characters together take one or two seconds to train. So every label change retrains everything.

**When a clip counts as confident.** A clip skips the line-by-line check by a person only when both of these hold:

1. Its confidence is at least 0.6.
2. It passes the similarity check. The cutoff is measured from the confirmed clips of the target character. For each confirmed clip, take its highest similarity to the other confirmed clips of the same character. Then take the 5th percentile of those values. If there are fewer than 20 confirmed clips, no cutoff can be measured. In that case no clip counts as confident, and the interface does not show the "may be a voice not seen before" note. It only says that the machine can only pick among the characters it already knows. The similarity check is skipped when the top-ranked choice is "Other", because an unseen voice is labeled "Other" anyway.

The small classifier only picks among the characters it already knows, so the second condition is required.

**Starting groups.** Clips that have no label yet are grouped with `anime-va`, average linkage and a threshold of 0.70. A person then names each whole group.

**Text of a line.** A subtitle line counts as the text of a clip when their times overlap by at least half of the shorter of the two. Two clips that are more than 3 seconds apart start a new scene.

**Picture and sound.** ffmpeg cuts one clip at a time. The picture is 360p H.264 with 0.5 seconds of extra padding before and after. The sound is the same span of the vocal track. Both are cached in each episode's `app_media/`. Cutting one picture takes more than half a second. So when a person looks at a line, the server first cuts, in the background, the lines within 60 seconds before and after it in the same episode. Nearer lines go first, and the cutting then continues forward in time to the end of the episode. Two threads run in parallel. When the person moves to another line, the whole queue is replaced. Measured on episode 3: a line that was not cut in advance takes 0.8 to 1.1 seconds to open. A line cut in advance takes about 0.1 seconds. When More context is on, a separate copy with 5 or 15 seconds of extra time on each side is cut. Picture and sound start at the same moment. Their file names carry `.ctx5` or `.ctx15`. The server's background queue does not cut these; only the page asks for the next three lines ahead. The first time, they take about 0.6 and 1.1 seconds. Each cut is written to a temporary file whose name carries the process number, then moved into place, so two apps open on the same project cannot write into one file.

**Export.** Cuts from the vocal track at the original sample rate, and evens out the loudness without clipping peaks. The formats are GPT-SoVITS `train.list` (each line is `path|character|language|text`), Style-Bert-VITS2 `esd.list`, or just one folder per character. The text, from either subtitle file, is cleaned of caption marks first ([what is removed](SUBTITLES.md#what-is-cleaned-automatically)).

**Separate text subtitles.** When the subtitles used for the clips are a translation, you can attach a separate original-language subtitle file to each episode. On export, the text is taken from that file. The clips themselves do not change:

- When attaching, the offset is measured. The display times of both subtitle files are drawn as timelines with 10 ms cells. One is slid against the other, and the shift with the most overlap is taken. If the overlap is below 0.6, or fewer than 95% of the clips touch any dialogue, the attach is refused.
- When subtitles are read, the lines inside one entry are split apart, and the entry's time is shared among the lines by character count. Speaker names, sound notes and other caption marks are removed, and a speaker name is kept apart ([what is removed](SUBTITLES.md#what-is-cleaned-automatically)). Two names count as the same person when one ends with the other, such as トウカイテイオー and テイオー.
- For a clip, every line that overlaps it by more than 0.1 seconds must mostly fall inside the clip: 70% or more of it, or extending less than 0.8 seconds past each end. Together the lines must cover more than half of the clip. Only then is the text counted as complete.
- A character's name in the subtitles is the most common name among the named lines that overlap her clips. It must make up more than half of them. A line with a different name that overlaps a clip by more than 0.2 seconds marks that clip as mixed with someone else's speech. When the character's name cannot be found, two or more different names touching a clip also count as mixed.
- Clips whose text is incomplete, or that are mixed with someone else's speech, are not exported. They are written to `rejected.tsv` in the export folder, with the character, episode, start and end times, the reason, the original text and the attached text.

## Data files

Each episode has a folder `workspace/episodes/<episode>/`:

- `episode.json` records the paths of the source and the audio tracks, and `subtitle_styles`, the styles the clips were cut from (episodes cut before this was recorded pick them again, which gives the same lines). `segments.json` records the clip IDs, the episode name, and the start and end times. For an episode with attached text subtitles, `episode.json` also has `text_subtitles` (the path), `text_subtitle_offset` (the offset in seconds), `text_subtitle_agreement` (the overlap) and `text_subtitle_marked` (how many lines still carry marks the cleaning does not know, with a few examples, or null).
- Voiceprints are stored in `embeddings/<model name>/`. The matrix and its metadata line up row by row. The cache is tied to the content of the clip files, the content of the analysis audio, the model name and the minimum length. If any of these changes, the cache must be recomputed. An old cache raises an error. It is never used silently.
- `app_media/` holds the picture and sound pieces the interface cuts.

The interface's labels are stored in the workspace folder `labels/`:

- `events.jsonl` is append-only. Each line is one batch of changes, and it records each clip's value before and after the change. An undo is also a batch, and it records which batch it undoes. The cast table `cast.json` is stored separately. When a batch also creates, renames or merges characters, the batch's `cast` field records it, and an undo restores the cast table as well. A new character that has no clips left after an undo is deleted. Replaying all the lines gives the current labels.
- `cast.json` is the cast table. It holds the name, whether a person gave the name (`named`), the color, the pattern number (`pattern`), the avatar file, and whether the character takes part in training. A character without a name is shown as "Character N". Giving it a name is a rename. Pattern numbers only grow and are never reused. When no avatar has been cropped, the default picture is drawn from the pattern number. Avatar images are stored in the `avatars/` folder next to it.

**Clip IDs are a hash of the episode name plus the start and end times. They do not depend on neighboring clips.** Re-cutting an episode makes its labels invalid.

## Code layout

```text
src/avoc/
  cli.py                   command entry point (also run by `python -m avoc`)
  doctor.py                machine checks, shown by `avoc doctor` and the welcome page
  project.py               data format for an episode and its clips, content fingerprints, cache folders
  pipeline.py              prepare and add episodes, attach video and subtitles, voiceprint cache
  audio.py                 voice separation, making the analysis copy, the speech timeline used to measure subtitle offset
  language.py              picks Chinese or English for messages the web page shows
  embeddings/extract.py    four voiceprint models and the minimum clip length
  stages/subtitle.py       read subtitles, pick dialogue styles, measure offset
  stages/captions.py       every rule for caption marks: take the spoken words and speaker out of a line
  stages/text_subtitle.py  attached text subtitles: split lines, measure offset, give clips their text
  stages/export.py         export at the original sample rate
  app/workspace.py         read the workspace: episodes, clips, text, scenes, assembled voiceprints
  app/labels.py            label records in the interface, undo, cast table
  app/model.py             small classifier and similarity check
  app/video.py             cut the short video pieces shown next to each line
  app/adding.py            add an episode from the interface: runs `avoc add` in a separate process
  app/picker.py            the "Browse…" buttons: opens the system's file window
  app/server.py            web server endpoints, starting groups, picture cutting, export
  app/static/              built front-end files, made from web/ (do not edit by hand)
web/src/
  main.tsx                 starts the page
  App.tsx                  views, shortcuts, saving labels in order, undo
  api.ts                   calls to the server and the shapes of its answers
  language.ts              Chinese or English: tr(Chinese, English)
  clips.ts                 who a line belongs to, and the lists of the Characters view
  components/              the stage, one line, avatars, the avatar cropper, help
  views/                   Groups, Scenes, Characters, Export, adding an episode, welcome page
```
