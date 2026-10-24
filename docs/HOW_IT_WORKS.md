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
| Too little voice | A clip shorter than 0.5 seconds. It stays in the clip table, but it is too short for a voiceprint, so the machine makes no guess for it and a person picks the character. |
| Skipped line | A clip shorter than 1 second with no other line within 0.5 seconds before or after it. It is hidden in Scenes by default and is not work to do. A short clip with other lines close by is not skipped. |
| Target character | A character the user wants to collect. Only target characters get names. Everyone else is labeled "Other". |
| Small classifier | A logistic regression trained on the manual labels, with voiceprints as input. There is one per target character. Its output is the probability that a clip is that target. |
| Confidence | The small classifier's probability for the top-ranked character. |
| Similarity check | Checks whether a clip is similar enough to the closest confirmed clip of the top-ranked character. If it is not, the speaker may be someone who has not been labeled yet. |
| Spoken language | The language the voices in an episode speak, such as Japanese. Exported text must be in it, because a voice model learns which sounds go with which words. |
| Main subtitles (主字幕) | The subtitle file an episode is cut from (`--subs`): each line becomes one clip, at its times. Best in the spoken language, so each clip's text is its own line. |
| Secondary subtitles (辅助字幕) | An optional subtitle file in a language the person reads, usually a translation (`--display-subs`; "display subtitles" in the code). While labeling, its line is shown in small gray type under each clip's main subtitle line, so the person understands what is said. It changes nothing in how clips are cut or who the machine thinks is speaking, and nothing is exported from it. |
| Workspace | The folder that the interface opens. Inside it are `episodes/` (one folder per episode), `labels/` (the labels made in the interface) and, unless another folder is picked, `exports/` (the exported datasets). |

## Flow

**Video and subtitles → separate voices → cut clips along subtitle lines → compute voiceprints → label and correct in the interface → export.**

`add` does the first steps in one command:

1. **Reading the subtitles**: The file is read whatever its text encoding: UTF-8 and UTF-16 directly, and older Chinese, Japanese, Korean and Western encodings by trying each and keeping the reading that looks most like real text. ASS, SRT, WebVTT and a few rarer formats are told apart by their content, not by the file extension. Then the dialogue [styles](#glossary) are picked: the main one is the style with the most lines among those whose lines appear across the whole episode (an opening song has many lines, but all at the start). Styles named after it, such as "Default - Top", and other spread-out styles with at least a quarter as many lines (the second language of bilingual subtitles) are dialogue too. Comment lines, vector drawings and lines over 20 seconds are dropped. `add` prints which styles it used and which it left out, `avoc styles <file>` shows each style with sample lines, and `--styles` overrides the choice.
2. **`prepare`**: Takes the audio from the video (or from a separate audio file given with `--audio` on the same timeline). When the video has several audio tracks (an original and a dub), it takes the one in the [spoken language](#glossary): the language given with `--spoken`, or else a Japanese track if there is one, else the track marked default, else the first. The spoken language comes from that track's language tag; with no tag, Japanese is taken and `add` says so. Separates the voices for the whole episode and keeps the original sample rate. Also makes a 16 kHz copy for analysis. Then adds this episode's offset to the subtitles, so **each subtitle line becomes one clip**. If `--offset` is not given, the offset is measured with speech detection. If the alignment is too weak, it stops with an error and does not quietly switch to another method. When the subtitles are in the spoken language alone (not bilingual), each entry is cut **one person at a time**: a line opened by a dash, or with a name other than the person before, starts a new clip, and a line with no mark goes on with the person before. The entry's time is shared among them by character count. Entries with the same text that follow each other with no gap (some subtitles break one line into several entries wherever another entry starts) count as one. `episode.json` records this as `"segmentation": "speaker_turns"`.
3. **Secondary subtitles** (`--display-subs`): when given, their dialogue styles are picked as above and their offset is measured against the main subtitles: the display times of both files are drawn as timelines with 10 ms cells, one is slid against the other, and the shift with the most overlap is taken. If the overlap is below 0.6 they are not attached, and `add` warns but still finishes.
4. **`embed`**: Computes a unit-length voiceprint for every clip that is at least 0.5 seconds long, once for each of the three models the interface uses. Shorter clips stay in the clip table, but they have no voiceprint.

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

The probability of "Other" is recorded as 1 minus the probability of the top target character. So the numbers do not always add up to 1. A training set has a few hundred to a few thousand clips. All target characters together take one or two seconds to train. So every label change retrains everything. A target character gets no guess at all until 10 of their lines are confirmed and at least one line is labeled as someone else: with fewer, the guesses are barely better than calling everyone "Other" ([measured](#how-many-labels-before-the-guesses-are-good)), and with no one to compare against, every line would come out as theirs. Until then the page says how many lines each target has, and asks for a few "Other" labels if there are none.

**When a clip counts as confident.** A clip skips the line-by-line check by a person only when both of these hold:

1. Its confidence is at least 0.6.
2. It passes the similarity check. The cutoff is measured from the confirmed clips of the target character. For each confirmed clip, take its highest similarity to the other confirmed clips of the same character. Then take the 5th percentile of those values. If there are fewer than 20 confirmed clips, no cutoff can be measured. In that case no clip counts as confident, and the interface does not show the "may be a voice not seen before" note. It only says that the machine can only pick among the characters it already knows. The similarity check is skipped when the top-ranked choice is "Other", because an unseen voice is labeled "Other" anyway.

The small classifier only picks among the characters it already knows, so the second condition is required.

### How many labels before the guesses are good

Measured once, for one character (Tokai Teio, `teo`). The confirmed labels of episodes 1 and 2 (636 lines, 159 of them Teio, the rest "Other"; "low quality" left out) were replayed one at a time, as a person labels them in Scenes from the start of episode 1. After each step the machine was retrained the way the interface does it, and its guesses were scored on episode 3, which it never trained on: 310 lines, 57 of them Teio. Saying "Other" for every line there is already right 82% of the time, so that is the number to beat.

The chance gap measures whether the probabilities can be taken at their word: lines the machine gives 80% should turn out to be Teio about 80% of the time. It is the average distance between the two, so 0 is perfect and 0.05 means about 5 points off. "Found" is the share of Teio's 57 lines that the machine named as Teio with confidence 0.6 or more.

| Lines labeled | Of them Teio | Right | Right when confident | Found | Chance gap |
| --- | --- | --- | --- | --- | --- |
| 1–29 | 0 | no guess yet | | | |
| 30 | 1 | 82% | 82% | 0% | 0.17 |
| 50 | 6 | 93% | 95% | 58% | 0.06 |
| 60 | 10 | 94% | 97% | 77% | 0.05 |
| 150 | 25 | 96% | 97% | 81% | 0.03 |
| 200 | 43 | 98% | 98% | 89% | 0.025 |
| 636 | 159 | 99% | 99% | 95% | 0.014 |

- The guesses become useful at about 10 Teio lines and 50 "Other": 94% right, and three quarters of her lines found.
- The probabilities can be trusted, to within about 3 points, from about 25 Teio lines (150 labeled).
- What counts is the number of Teio lines, not the total. Labeled in random order, Teio turns up sooner: 20 lines (about 6 Teio) give 94% right, and the chance gap drops under 0.03 by about 80 lines.
- So the interface starts guessing a target at 10 confirmed lines of them (see above), and counts no line as confident before 20.

Not measured: other characters, episodes from another season, and labeling in Groups. To repeat it on a workspace: `uv run python scripts/replay_labels.py workspace teo --train ep01,ep02 --test ep03` ([script](../scripts/replay_labels.py)).

**Starting groups.** Only clips still to do are grouped: not labeled yet, not skipped, with a voiceprint, and without a guess the machine is confident about. These are the lines "Only to do" lists in Scenes, apart from those with too little voice. They are grouped with `anime-va`, average linkage and a threshold of 0.70. A person then names each whole group.

**Text of a line.** A subtitle line counts as the text of a clip when their times overlap by at least half of the shorter of the two. Two clips that are more than 3 seconds apart start a new scene.

**Picture and sound.** ffmpeg cuts one clip at a time. The picture is 360p H.264 with 0.5 seconds of extra padding before and after. The sound is the same span of the vocal track. Both are cached in each episode's `app_media/`. Cutting one picture takes more than half a second. So when a person looks at a line, the server first cuts, in the background, the lines within 60 seconds before and after it in the same episode. Nearer lines go first, and the cutting then continues forward in time to the end of the episode. Two threads run in parallel. When the person moves to another line, the whole queue is replaced. Measured on episode 3: a line that was not cut in advance takes 0.8 to 1.1 seconds to open. A line cut in advance takes about 0.1 seconds. When More context is on, a separate copy with 5 or 15 seconds of extra time on each side is cut. Picture and sound start at the same moment. Their file names carry `.ctx5` or `.ctx15`. The server's background queue does not cut these; only the page asks for the next three lines ahead. The first time, they take about 0.6 and 1.1 seconds. Each cut is written to a temporary file whose name carries the process number, then moved into place, so two apps open on the same project cannot write into one file.

**Export.** Cuts from the vocal track at the original sample rate, and evens out the loudness without clipping peaks. The formats are GPT-SoVITS `train.list` (each line is `path|character|language|text`, with the language as `ja`, `zh`, `en` or `ko`), or just one folder per character. For GPT-SoVITS, the text is always in the episode's spoken language, cleaned of caption marks ([what is removed](SUBTITLES.md#what-is-cleaned-automatically)). Clips without such text are left out. The audio-only format needs no text.

**Text in the spoken language.** Each clip's text is matched when the workspace opens, so the Scenes and Characters views show it under the subtitle line, and mark a target character's clip that would be left out with "No text to export" and the reason. The text comes only from the main subtitles, so they must be in the spoken language. Bilingual subtitles count: only their lines in the spoken language are used. An episode cut one person at a time ([flow](#flow)) uses the same pieces as its clips, so each clip's text is exactly its own line. An episode cut from a translation has no text at all and can only be exported as sound; to get text, delete it and add it again with subtitles in the spoken language as the main subtitles.

Each clip shows its own main subtitle line in large type. With [secondary subtitles](#glossary), the line of theirs that overlaps it (by the same rule as under "Text of a line") is shown in small gray type under it. The spoken text is shown under that only when it differs from the main line and the text is exported at all: with "Sound only", nothing about exported text is shown.

The language of each line is worked out from its letters. Two or more kana mean Japanese and two or more Hangul mean Korean. Any other line (Chinese characters only, Latin letters, digits) takes the language most common at its place in the file: the same style and the same line number within the entry. So in a file with Chinese on the first line and Japanese on the second, the Japanese line ６連勝 still counts as Japanese. A file has a language when at least 30% of its lines are in it. The interface's add form and the Export view show the language of each file.

How the text is matched to clips. The clips themselves do not change:

- When subtitles are read, the lines inside one entry are split apart, and the entry's time is shared among the lines by character count. Speaker names, sound notes and other caption marks are removed, and a speaker name is kept apart ([what is removed](SUBTITLES.md#what-is-cleaned-automatically)). Two names count as the same person when one ends with the other, such as トウカイテイオー and テイオー.
- For a clip, every line that overlaps it by more than 0.1 seconds must mostly fall inside the clip: 70% or more of it, or extending less than 0.8 seconds past each end. Together the lines must cover more than half of the clip. Only then is the text counted as complete.
- A character's name in the subtitles is the most common name among the named lines that overlap her clips. It must make up more than half of them. A line with a different name that overlaps a clip by more than 0.2 seconds marks that clip as mixed with someone else's speech. When the character's name cannot be found, two or more different names touching a clip also count as mixed. So one subtitle entry with two speakers is left out.
- Clips whose text is incomplete, or that are mixed with someone else's speech, are not exported. They are written to `rejected.tsv` in the export folder, with the character, episode, start and end times, the reason, the main subtitle line and the text found.

## Data files

Each episode has a folder `workspace/episodes/<episode>/`:

- `episode.json` records the paths of the source and the audio tracks, and `subtitle_styles`, the styles the clips were cut from (episodes cut before this was recorded pick them again, which gives the same lines). It also records `audio_track` (which audio track of the video, from 0), `spoken_language` (`ja`, `zh`, `en` or `ko`) and `spoken_from` (`track` for the track's tag, `person`, or `assumed`); episodes added before these were recorded count as Japanese, assumed. `segments.json` records the clip IDs, the episode name, and the start and end times. `segmentation` is `speaker_turns` for an episode cut one person at a time, and `subtitle_lines` otherwise. With secondary subtitles, it also has `display_subtitles`, `display_subtitle_styles`, `display_subtitle_offset` and `display_subtitle_agreement`.
- Voiceprints are stored in `embeddings/<model name>/`. The matrix and its metadata line up row by row. The cache is tied to the content of the clip files, the content of the analysis audio, the model name and the minimum length. If any of these changes, the cache must be recomputed. An old cache raises an error. It is never used silently.
- `app_media/` holds the picture and sound pieces the interface cuts.

The interface's labels are stored in the workspace folder `labels/`:

- `events.jsonl` is append-only. Each line is one batch of changes, and it records each clip's value before and after the change. An undo is also a batch, and it records which batch it undoes. The cast table `cast.json` is stored separately. When a batch also creates, renames or merges characters, the batch's `cast` field records it, and an undo restores the cast table as well. A new character that has no clips left after an undo is deleted. Replaying all the lines gives the current labels.
- `cast.json` is the cast table. It holds the name, whether a person gave the name (`named`), the color, the pattern number (`pattern`), the avatar file, and whether the character takes part in training. A character without a name is shown as "Character N". Giving it a name is a rename. Pattern numbers only grow and are never reused. When no avatar has been cropped, the default picture is drawn from the pattern number. Avatar images are stored in the `avatars/` folder next to it.
- `purpose.json` records what the voices are for, `{"purpose": "tts"}` (reading text aloud) or `"audio"` (sound only). It is written once, when the add form starts the first episode, and never changed ([how](USAGE.md#labeling-and-correction-interface)).

**Clip IDs are a hash of the episode name plus the start and end times. They do not depend on neighboring clips.** Re-cutting an episode makes its labels invalid.

## Code layout

```text
src/avoc/
  cli.py                   command entry point (also run by `python -m avoc`)
  doctor.py                machine checks, shown by `avoc doctor`; problems also show in the "Add an episode" form
  project.py               data format for an episode and its clips, content fingerprints, cache folders
  pipeline.py              prepare and add episodes, attach video and subtitles, voiceprint cache
  audio.py                 audio tracks, voice separation, the analysis copy, the speech timeline used to measure subtitle offset
  language.py              picks Chinese or English for messages the web page shows
  embeddings/extract.py    four voiceprint models and the minimum clip length
  stages/subtitle.py       read subtitles, pick dialogue styles, measure offset
  stages/captions.py       every rule for caption marks: take the spoken words and speaker out of a line
  stages/text_subtitle.py  text in the spoken language: split lines, give clips their text
  stages/text_language.py  the language of subtitle lines and of audio track tags
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
  index.css                Tailwind, and the theme's colors and fonts
  components/              the top and bottom bars, the stage, one line, avatars, the avatar cropper, help,
                           and small shared parts (chips, pills, hints, rows of joined buttons)
  components/ui/           shadcn/ui components, copied in by its command
  views/                   Groups, Scenes, Characters, Export, adding an episode, the first page of an empty workspace
web/e2e/                   browser tests, and the script that serves a small made-up workspace for them
scripts/replay_labels.py   replays a workspace's labels to measure how fast the guesses become good
```
