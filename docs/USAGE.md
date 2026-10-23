# Commands

All the commands are listed only here. For how each step works inside, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md). `uv run avs --help` lists all the commands, and `uv run avs <command> --help` lists the options of one command.

| Section | What it does |
| --- | --- |
| [Set up](#set-up) | Before the first run |
| [Processing a new episode](#processing-a-new-episode) | Separate voices, cut clips, compute voiceprints, check coverage |
| [Extending clips](#extending-clips) | Add the dialogue lines that were missed into an old clip table |
| [Labeling and correction interface](#labeling-and-correction-interface) | The daily main workflow: label a few lines, let the machine guess, fix its wrong guesses, export |
| [Labeling](#labeling) | The old page used for blind labeling of the held-out test set |
| [Grouping, scoring, export](#grouping-scoring-export) | Group, score and export by machine, without the interface. Kept for comparison |
| [Comparison experiments](#comparison-experiments) | Sweep thresholds, measure drift, check whether pairs can be told apart, nearest-neighbor diagnosis |
| [Checks](#checks) | Checks to run before committing |

## Set up

You need FFmpeg on your `PATH`. For the GPU setup and notes on each model, see [TOOLS.md](TOOLS.md).

```powershell
uv sync --locked
uv run avs doctor
```

`doctor` lists each item in turn: the graphics card, FFmpeg, the voice separation model, the Hugging Face token, and the free disk space. Items marked "missing" must be fixed first. Items marked "optional" can be left alone and the tool still works.

## Processing a new episode

```powershell
uv run avs add runs "D:/_search/ani/uma/[DHR][Uma Musume S2][08][BIG5][1080P][HEVC_AAC].mp4" --subs "data/ass/uma/[FLsnow][umamusumeS2][08][AVC_AAC][WEBRIP][1080p].chs.ass" --audio data/raw/uma_s2_08.flac --offset -0.95
```

`add` does everything in one command: it extracts the audio track, separates the voices, cuts clips along the subtitle lines, and then computes the three voiceprints that the interface needs. If the episode name is left out, it uses the next unused `epNN` in the workspace. You can also name it with `--name`. If you give `--text-subs <Japanese subtitle file>`, the dialogue text used for export is attached in the same step (the same as `set-text-subtitles` below). If the run stops halfway (for example, because there is not enough GPU memory), fix the problem and run the same command again. It picks up where it stopped: clips that are already cut and voiceprints that are already computed are not recomputed. If the clip-cutting step itself fails, the half-built folder is deleted.

Both the video and the subtitles are required. The audio track is extracted from the video by default. If you have a lossless audio track on the same timeline, give it with `--audio`. If its length differs from the video by more than 0.5 seconds, it is refused. `--device` defaults to `auto`: it uses the NVIDIA GPU if there is one, and otherwise the CPU. On the CPU, voice separation switches to full precision. The `--device` option of `prepare` and `embed` works the same way.

**Giving `--offset` directly is recommended.** For the same source and the same subtitle group, the offset is stable (measured on episodes 1 to 3: -0.95, -0.96, -0.96). When it is given, speech detection does not run at all. If it is not given, the offset is measured with pyannote. That requires you to accept the terms on the [model page](https://huggingface.co/pyannote/speaker-diarization-community-1) first, and then to log in to Hugging Face with `uv run hf auth login`. Without a token, `add` and `prepare` report the error right at the start. They do not stop halfway through.

If you prefer to run the steps one at a time, `add` is equal to the following:

```powershell
uv run avs prepare "video" --subs "subtitles" --name ep08 --out runs/episodes/ep08 --offset -0.95
uv run avs embed runs/episodes/ep08 --model anime-va
uv run avs embed runs/episodes/ep08 --model anime-char
uv run avs embed runs/episodes/ep08 --model redimnet2-b6
```

After cutting, check the coverage:

```powershell
uv run avs coverage runs/episodes/ep08 --subtitle "data/ass/uma/[FLsnow][umamusumeS2][08][AVC_AAC][WEBRIP][1080p].chs.ass" --out runs/coverage/ep08
```

`coverage` checks whether the cutting is right. The number of dialogue lines that have a clip should equal the total number of dialogue lines (episode 3: 375 of 375). It also cuts the dialogue that has no clip into audio files. These go into two folders, `below_floor` (the line itself is too short) and `no_speech_found` (the line is long enough, but no clip was cut from it). It also writes `lines.txt` and `report.json`.

## Extending clips

```powershell
uv run avs extend runs/episodes/ep02 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][02][HEVC_FLAC][BDRIP].chs.ass"
uv run avs embed runs/episodes/ep02
```

Adds the dialogue lines in the subtitles that have no matching clip into the clip table. It only adds and never changes, so existing labels stay valid. The voiceprint cache is invalid once the clip table changes, so `embed` must be run again. Narration and cheers that get added are not filtered here. A person labels them while labeling.

## Labeling and correction interface

The workspace is a folder. Its `episodes/` subfolder holds the episodes (the output of `add` or `prepare`), and labels are saved automatically in `labels/`. This repo uses `runs/` as the workspace.

```powershell
uv run avs app runs
```

Open `http://127.0.0.1:8765` in your browser. `--port` changes the port. `--no-open` stops the browser from opening by itself. `--model` can be repeated, to use only the named voiceprint models. The part of the address after `#` records the current view, episode, character and selected line, so after a refresh you return to the same spot. Episodes whose voiceprints are not all computed (usually because `add` was interrupted) are not loaded. They are listed on the command line at startup, and the other episodes work as usual. When the workspace has no episodes at all, the page shows an `add` command that you can copy.

Give names only to the people you want to collect (the target characters). Label everyone else "Other" with the Q key, including anyone you are not sure is a target. Clips where several people speak and none of them is a target are also labeled "Other", and so are clips that are not speech, such as cheers and sound effects. The target character's own laughs and sighs count as the target's voice, so label them as the target. Each target character has two options, chosen in one go. The number key gives the clean target. Shift plus the same number gives "target, low quality". Use the low-quality option for clips with heavy background sound or with several people talking at once. Those clips are not used to recognize the character. They are skipped on export and written to `rejected.tsv`. With two target characters, the bottom bar has 5 options in all: four for the two targets (clean and low quality for each), plus "Other". Next to each target character's guess on the left there is also a "Low quality" button. When you change a clip to the clean target or to "Other", "Low quality" is removed automatically. There can be several target characters. You can add or remove them at any time in the Characters view. For how existing labels are handled when you add or remove a target, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface).

- **Groups (G)**: start here when there are no labels yet. The machine puts clips that sound alike into one group, so you can label a whole group at once. Click the avatar of an existing target character to label the group as that character. "New character" makes the group a new target character (the name can be left blank). The "Other" button labels the whole group "Other". You can also use the keys to label only the selected line. A labeled line stays in the group and shows what it was labeled as. The group buttons only act on lines that are not labeled yet. Undoing with Z restores the group as it was.
- **Scenes (S)**: lists all the lines by episode and scene, in order. The left side shows the picture and the machine's ranking of its guesses. "Vocals only" is on by default: the picture plays, but the sound switches to the separated vocals. To hear the original sound, click "Original sound". Beside it you can choose 1x or 2x speed, and the reference audio plays at the same speed. Both settings are remembered, so they stay after a refresh. Pressing Space, or clicking the selected line again, replays it. When you cannot tell who is speaking, press L to play the line with 5 seconds of extra time on each side (this is "More context"). Press L again for 15 seconds, and again to go back to normal. Moving to another line goes back to normal automatically. Each target character has a reference sound. Enter accepts the first guess. The number keys pick a target character from the bottom bar. Q labels "Other". `/` searches for a character or creates one. F shows only "Only to do". Lines shorter than 1 second, with no other dialogue within 0.5 seconds on either side, are marked "too short, skipped by default". They do not count as work to do, and they are hidden by default in "Whole episode". Click "Show short lines" to list them. You can still label them if you want.
- **Characters (O)**: at the top of the left side are the target characters. Below them are characters that are no longer targets but still have labels. The last row is "Other". Each row shows, on the right, how many lines have been confirmed, how many the machine assigned to it, and the total length of the confirmed dialogue. Open a character to see first the lines the machine assigned to it, starting with the least confident. You can play them one after another. When you hear a wrong one, label it as the right person, or press Q for "Other", and it leaves this list. After listening to the rest, press Shift+Enter ("Confirm the other N lines") to confirm the remaining lines. Below that is "Maybe missed": lines the machine did not assign to this character, but that might be it. They start with the most similar, and are labeled like any other line. Here you can also rename characters, merge them, set an avatar, and set or unset a target character. "Other" can also be opened. Each line there shows which target character the machine thinks is closest, and with what probability. Confirmed lines are sorted starting from those closest to a target, so wrong labels show up first.
- **Export (E)**: choose the character and the format (GPT-SoVITS, Style-Bert-VITS2, or one folder per character). You can export only the lines that a person has confirmed, or also include the lines the machine is confident about. When the subtitles used for cutting are Chinese translations and you want to train a Japanese model, set "Where the text comes from" to "Separate text subtitles for each episode". Then paste the path of each episode's Japanese subtitle file below, and click "Align and attach". You can also attach them with the `set-text-subtitles` command below. Clips whose dialogue text cannot be matched are not exported. The details are in `rejected.tsv` in the export folder.

Identifying people mainly relies on avatars, and names can be left blank:

- Press N to label the current line as a new character. It first gets a temporary name such as "Character 1" or "Character 2". Later, in the Characters view, click "Name it" to fill in the real name.
- A character with no avatar shows a picture generated from its number. The background color, shape and pattern all change together, so different characters are easy to tell apart at a glance.
- Cropping an avatar: when a new character is created and there is a picture, the cropper pops up straight away. Later, click the avatar to crop it. You can do this from the confirmed lines on the left, or from the avatar at the top of the Characters view. Drag the box to move it. Drag the bottom-right corner or use the scroll wheel to zoom. Use the slider to change the frame, and press Enter to save.

Each label is saved to disk and the model is retrained right away. Backspace (or Delete) clears the label of the current line and returns it to the machine's guess. Confirmed lines also have a "Clear label" button on the left. Z undoes the last step, and you can keep pressing it to go further back. Creating, renaming and merging characters are also undone. Avatars and setting or unsetting a target character are not part of undo. Press `?` to see all the shortcuts. The page uses a light color scheme by default. You can switch to dark mode at the top right. Next to it, the EN / 中文 button switches the page between English and Chinese; the first time, the page follows the browser's language. Messages from the server, such as errors, follow the page language. Both choices are remembered in the browser.

Commands for filling in information for older episodes:

```powershell
uv run avs set-video runs/episodes/ep01 "D:/_search/ani/uma/[DHR][Uma Musume S2][01][BIG5][1080P][HEVC_AAC].mp4"
uv run avs set-subtitles runs/episodes/ep01 "data/ass/uma/[FLsnow][UmamusumeS2][01][HEVC_FLAC][BDRIP].chs.ass"
uv run avs set-text-subtitles runs/episodes/ep01 "data/subtitles/uma_s2/ja/Netflix/ウマ娘.プリティーダービー.S02E01.トウカイテイオー.WEBRip.Netflix.ja[cc].srt"
uv run avs import-labels runs --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --target teo
uv run avs migrate-targets runs --target teo
```

- `set-video`: records the video for an episode that was processed before `prepare` required it. If the length does not match the audio track, it is refused.
- `set-subtitles`: adds subtitles to an episode that has none recorded. The offset is worked out from the existing clips, and the dialogue text is found by matching the times that overlap.
- `set-text-subtitles`: attaches a second subtitle file (ASS or SRT) to an episode. On export, the dialogue text is taken from it. The offset is measured automatically. If it does not match the subtitles used for cutting, it is refused. Subtitles from Netflix or Amazon are preferred. Subtitles recorded from TV carry symbols such as 🎤, and these are not removed.
- `import-labels`: imports the old manual archives into the label records in one go. It can only be used while the label records are still empty. Imports cannot be undone. If you give `--target`, follow it with `migrate-targets` below.
- `migrate-targets`: keeps only the given target characters (the option can be repeated), and changes the labels of all other characters to "Other". Before changing anything, it copies the label records and the cast table in `labels/` as they are into `labels/archive-date-time/`. A migration cannot be undone with Z. To recover the old names, use the archive.

## Labeling

Episodes 1 to 3 were blind-labeled with this old page, which does not show the machine's guesses. Now that the held-out test has been cancelled, new episodes are labeled in the correction interface. This page is kept as a backup. The labeling rules (why only the picture counts, and why the page gives no machine answers) are in [HISTORY.md](HISTORY.md#labeling). The archive files are described in [annotations/README.md](../annotations/README.md).

```powershell
uv run avs label runs/episodes/ep04 --archive annotations/ep04-full.json --all --known annotations/ep03-full.json --known annotations/names.json --video "D:/_search/ani/uma/[DHR][Uma Musume S2][04][BIG5][1080P][HEVC_AAC].mp4"
```

Check each name against the picture. Each press is saved to the manual archive right away.

- `--all`: labels all the clips of this episode, going through them in time order. Without it, `--count` clips are picked at random. If new clips are added to the clip table later, running `--all` again appends them to the existing archive with empty labels. Clips that are already labeled are not touched.
- `--known`: where the clickable character names on the page come from. It can be repeated. If you give a manual archive, the clips in it can be played back on the page. If you give `annotations/names.json`, a list of names only, you get names only. Names are sorted by how many lines they appear in. The number keys 1 to 9 select the first nine.
- `--video`: plays the picture for the current clip, with 0.5 seconds of extra time on each side. ffmpeg cuts each clip only when you reach it (measured: a 2 to 3 second clip takes less than half a second), and it also pre-cuts the next one. The output is converted to 360p H.264, about 46 MB per episode.

  **The video and the audio track must be on the same timeline.** `data/raw/*.flac` is extracted from these mp4 files. Their lengths match exactly, and the waveform alignment shift is 0 ms. Check this before switching sources, or the picture will show the wrong person.

Page operations:

- Character names are shown as small blocks. Click one to label the current clip. Special labels are also shown as blocks. Otherwise, clips labeled "multiple people" could never be found again for review.
- Clicking the number to the right of a name opens a panel that lists all the clips under that name, by episode and time. In the current round, clicking one jumps to it. In an old archive, clicking one plays it in place, using a separate player so that the clip being labeled is not interrupted. In the panel you can rename a name, remove labels in bulk, or drag a single clip onto another name to change its owner.
- Type a new name in the filter box and click "+ Create this name" to create it first, then drag clips onto it. Unused names, and names removed from the list, only affect the current page. They are not saved to disk.

## Grouping, scoring, export

```powershell
uv run avs group runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --out runs/groups/uma-next.json
uv run avs evaluate runs/groups/uma-next.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --out runs/groups/uma-next-evaluation.json
uv run avs export runs/groups/uma-next.json --out out/uma-next
```

Options of `group`:

- `--threshold`: if not given, the model's own default threshold is used, and it is printed.
- `--relative`: sets the threshold from the pool's own distances (see the [glossary](HOW_IT_WORKS.md#glossary)). It has not been checked on a held-out test, so it is off by default. For the current status, see [STATUS.md](STATUS.md).
- `--model`: `anime-va` (default), `redimnet2-b6`, `anime-char` or `wespeaker-resnet293`. Changing the model means sweeping the threshold again.
- `--method`: default `average`. The others are `single`, `complete`, `mutual_knn` and `two_stage`. All are ruled out, and kept only for recomputing.

Group files and export folders always get new names, so that old audio does not get mixed into new results.

## Comparison experiments

Numbers picked out using manual labels only count as exploration. They must be checked on a separate set of data that took no part in choosing them.

**Sweep thresholds; compare models and merge rules:**

```powershell
uv run avs compare runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --model redimnet2-b6 --method average --low 0.25 --high 1.15 --out runs/comparison-next.json
```

It first checks that each model covers the same clips. `--low` and `--high` must be given on each model's own similarity scale. The default 0.20 to 0.90 was set for `redimnet2-b6`, and it is almost meaningless for `anime-va`.

**Measure how scores change as the clip pool grows:**

```powershell
uv run avs drift runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --scored ep03 --annotation annotations/ep03-full.json --out runs/drift-next.json --steps 9 --seeds 8
```

The scored episode always stays in the pool in full. Only clips from other episodes are added to the pool. `--steps` sets how many stages there are, and `--seeds` sets how many random draws are made at each stage. The report puts two lines side by side: a fixed threshold, and a threshold set from the pool. `--multiplier` can try other levels of strictness.

**Hold out by episode, and assign clips directly to character names:**

```powershell
uv run avs classify-check runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --test ep03 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --model anime-va --model anime-char --model redimnet2-b6 --out runs/classify/next.json
```

Labels from the `--test` episode are not used for training. They are only used for scoring. Labels from all the other episodes are used for training. `--model` can be repeated. With several models, their voiceprints are joined together. The cache for each model must be computed beforehand with `avs embed`. The report puts three methods side by side: "closest single clip", "character average" and "small classifier". Each one comes with its per-clip predictions.

**Compare only how well same-character and different-character pairs separate, without grouping:**

```powershell
uv run avs scores runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --norm none --out runs/score-next.json
```

The report gives ranking accuracy and equal error rate, split by clip length and by whether a pair crosses episodes. `--norm` can be repeated (`none`, `snorm` or `asnorm`). The last two are score normalization, which is ruled out. `--window` reads voiceprints computed with a different minimum clip length.

**Nearest-neighbor search and distance distribution:**

```powershell
uv run avs diagnose runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --groups runs/groups/uma3.json --out runs/diagnosis-next
```

The output is a report, the distances for all label pairs, and error examples under `examples/` that you can listen to.

**Commands left over from ruled-out routes**, kept only for recomputing: `avs embed --window` (pads short clips with the neighboring audio, stored in `embeddings/<model>@w<seconds>`), `avs references` (a few identity references), and `avs label-plan` (labels only the clips whose candidate changed).

## Checks

The commands to run before committing are listed in [CLAUDE.md](../CLAUDE.md#checks). The type checker is [ty](https://github.com/astral-sh/ty). It is not in the project dependencies, and it is installed on this machine with `uv tool install ty`. CI pins it at version 0.0.91.
