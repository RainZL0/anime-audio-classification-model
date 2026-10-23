# Commands

All the commands are listed only here. For how each step works inside, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md). `uv run avoc --help` lists all the commands, and `uv run avoc <command> --help` lists the options of one command.

| Section | What it does |
| --- | --- |
| [Set up](#set-up) | Before the first run |
| [Processing a new episode](#processing-a-new-episode) | Separate voices, cut clips, compute voiceprints |
| [Labeling and correction interface](#labeling-and-correction-interface) | The daily main workflow: label a few lines, let the machine guess, fix its wrong guesses, export |
| [Checks](#checks) | Checks to run before committing |

## Set up

You need FFmpeg on your `PATH`. For the GPU setup and notes on each model, see [TOOLS.md](TOOLS.md).

```powershell
uv sync --locked
uv run avoc doctor
```

`doctor` lists each item in turn: the graphics card, FFmpeg, the voice separation model, the Hugging Face token, and the free disk space. Items marked "missing" must be fixed first. Items marked "optional" can be left alone and the tool still works.

## Processing a new episode

```powershell
uv run avoc add runs "D:/_search/ani/uma/[DHR][Uma Musume S2][08][BIG5][1080P][HEVC_AAC].mp4" --subs "data/ass/uma/[FLsnow][umamusumeS2][08][AVC_AAC][WEBRIP][1080p].chs.ass" --audio data/raw/uma_s2_08.flac --offset -0.95
```

The interface can also add an episode, with the same steps ([how](#labeling-and-correction-interface)). `add` does everything in one command: it extracts the audio track, separates the voices, cuts clips along the subtitle lines, and then computes the three voiceprints that the interface needs. If the episode name is left out, it uses the next unused `epNN` in the workspace. You can also name it with `--name`. If you give `--text-subs <Japanese subtitle file>`, the dialogue text used for export is attached in the same step (the same as `set-text-subtitles` below). If the run stops halfway (for example, because there is not enough GPU memory), fix the problem and run the same command again. It picks up where it stopped: clips that are already cut and voiceprints that are already computed are not recomputed. Text subtitles given with `--text-subs` are noted in the episode before the voiceprints start, so they are still attached if you leave `--text-subs` out the second time. If the clip-cutting step itself fails, the half-built folder is deleted.

Both the video and the subtitles are required. The subtitles can be in any common text encoding, and the dialogue [styles](HOW_IT_WORKS.md#glossary) are picked automatically ([how](HOW_IT_WORKS.md#flow)). `add` prints the styles it used and the ones it left out. To check a file first, run `uv run avoc styles "subtitles"`: it lists each style with its line count, time range and sample lines, and marks the ones that would be picked with `*`. If the choice is wrong, give the styles yourself, for example `--styles "Default,Default - Top"`. In the app's add form, the same list appears under the subtitle path once it is filled in, with check boxes. The audio track is extracted from the video by default. If you have a lossless audio track on the same timeline, give it with `--audio`. If its length differs from the video by more than 0.5 seconds, it is refused. `--device` defaults to `auto`: it uses the NVIDIA GPU if there is one, and otherwise the CPU. On the CPU, voice separation switches to full precision. The `--device` option of `prepare` and `embed` works the same way.

**Giving `--offset` directly is recommended.** For the same source and the same subtitle group, the offset is stable (measured on episodes 1 to 3: -0.95, -0.96, -0.96). When it is given, speech detection does not run at all. If it is not given, the offset is measured with pyannote. That requires you to accept the terms on the [model page](https://huggingface.co/pyannote/speaker-diarization-community-1) first, and then to log in to Hugging Face with `uv run hf auth login`. Without a token, `add` and `prepare` report the error right at the start. They do not stop halfway through.

If you prefer to run the steps one at a time, `add` is equal to the following:

```powershell
uv run avoc prepare "video" --subs "subtitles" --name ep08 --out runs/episodes/ep08 --offset -0.95
uv run avoc embed runs/episodes/ep08 --model anime-va
uv run avoc embed runs/episodes/ep08 --model anime-char
uv run avoc embed runs/episodes/ep08 --model redimnet2-b6
```

## Labeling and correction interface

The workspace is a folder. Its `episodes/` subfolder holds the episodes (the output of `add` or `prepare`), and labels are saved automatically in `labels/`. This repo uses `runs/` as the workspace.

```powershell
uv run avoc app runs
```

Open `http://127.0.0.1:8765` in your browser. `--port` changes the port. `--no-open` stops the browser from opening by itself. `--model` can be repeated, to use only the named voiceprint models. The part of the address after `#` records the current view, episode, character and selected line, so after a refresh you return to the same spot. Episodes whose voiceprints are not all computed (usually because `add` was interrupted) are not loaded. They are listed on the command line at startup, and the other episodes work as usual. When the workspace has no episodes at all, the page opens on a welcome page: what the tool does in four steps, the same machine checks as `doctor`, and a form to add the first episode.

Adding an episode from the interface: on the welcome page, or with "+ Add an episode…" at the bottom of the episode menu. Paste the paths of the video, the dialogue subtitles and, if you want, the Japanese text subtitles. The offset box is filled in with the last episode's offset. Start runs the same `avoc add` as on the command line, in a separate process. The progress lines show as it goes, and library warnings show only if it fails. Separating the voices of one episode took about 12 minutes on an RTX 4060 Laptop GPU; the voiceprints take under a minute. You can close the dialog and keep labeling; a button at the top shows that it is still running, and the new episode appears in the menu when it is done. Stop ends it. If it stops before the clips are cut, the half-built folder is deleted. Otherwise the episode is listed under "Unfinished episodes" with a "Carry on" button, which reruns it with the files it recorded. Only one episode is added at a time.

Give names only to the people you want to collect (the target characters). Label everyone else "Other" with the Q key, including anyone you are not sure is a target. Clips where several people speak and none of them is a target are also labeled "Other", and so are clips that are not speech, such as cheers and sound effects. The target character's own laughs and sighs count as the target's voice, so label them as the target. Each target character has two options, chosen in one go. The number key gives the clean target. Shift plus the same number gives "target, low quality". Use the low-quality option for clips with heavy background sound or with several people talking at once. Those clips are not used to recognize the character. They are skipped on export and written to `rejected.tsv`. With two target characters, the bottom bar has 5 options in all: four for the two targets (clean and low quality for each), plus "Other". Next to each target character's guess on the left there is also a "Low quality" button. When you change a clip to the clean target or to "Other", "Low quality" is removed automatically. There can be several target characters. You can add or remove them at any time in the Characters view. For how existing labels are handled when you add or remove a target, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface).

The tabs at the top come in two boxes. The first box holds the episode menu with Groups and Scenes, which show only that episode. The second box, "All episodes", holds Characters and Export, which cover every episode, so switching the episode does not change them.

- **Groups (G)**: start here when there are no labels yet. The machine puts clips that sound alike into one group, so you can label many lines at once. Tick the lines of one person, or press "Select all"; Shift+click ticks every line between the last ticked one and this one. Then pick who they are from the row of buttons under the group: a target character (the one the machine guesses most often in this group comes first, marked the same way as its top guess on the left), "Other", or "New character", which makes them a new target character whose name can be filled in later. To use a name not in that row, type it in the box below, existing or new, and press "Use this name". When a group mixes several people, tick and label them in turns. The number keys, Q, N, the bottom bar and `/` search also label the ticked lines while any are ticked; with none ticked, they label only the line playing. A labeled line stays in the group, shows what it was labeled as, and can no longer be ticked. Undoing with Z restores the group as it was.
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
uv run avoc set-video runs/episodes/ep01 "D:/_search/ani/uma/[DHR][Uma Musume S2][01][BIG5][1080P][HEVC_AAC].mp4"
uv run avoc set-subtitles runs/episodes/ep01 "data/ass/uma/[FLsnow][UmamusumeS2][01][HEVC_FLAC][BDRIP].chs.ass"
uv run avoc set-text-subtitles runs/episodes/ep01 "data/subtitles/uma_s2/ja/Netflix/ウマ娘.プリティーダービー.S02E01.トウカイテイオー.WEBRip.Netflix.ja[cc].srt"
```

- `set-video`: records the video for an episode that was processed before `prepare` required it. If the length does not match the audio track, it is refused.
- `set-subtitles`: adds subtitles to an episode that has none recorded. The offset is worked out from the existing clips, and the dialogue text is found by matching the times that overlap.
- `set-text-subtitles`: attaches a second subtitle file (ASS or SRT) to an episode. On export, the dialogue text is taken from it. The offset is measured automatically. If it does not match the subtitles used for cutting, it is refused. Subtitles from Netflix or Amazon are preferred. Subtitles recorded from TV carry symbols such as 🎤, and these are not removed.

## Checks

The commands to run before committing are listed in [CLAUDE.md](../CLAUDE.md#checks). The type checker is [ty](https://github.com/astral-sh/ty). It is not in the project dependencies, and it is installed on this machine with `uv tool install ty`. CI pins it at version 0.0.91.
