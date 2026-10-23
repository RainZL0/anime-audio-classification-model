# Settled approaches and ruled-out paths

This page lists only the conclusions. Each one has a one-sentence reason. Numbers and the process are linked to [EXPERIMENTS.md](EXPERIMENTS.md). To overturn one of these, bring new data first, then change it here. Approaches that are not settled yet are not listed here. The questions still being tested are in [STATUS.md](STATUS.md).

## Settled

**Goal and scope**

- The unit of collection is a **character**, not a voice actor. New characters are allowed. Do not force an unknown character into a known name.
- Settle identity classification first. Interjections and noise come later.
- Subtitles give only the time boundaries and the dialogue text. No speech-to-text or text recognition is added.
- Do not fine-tune the voiceprint models. There are only labels for a few episodes, which is not enough. For when to reconsider this, see [ROADMAP.md](ROADMAP.md#direction).

**Cutting clips**

- **Always cut along whole subtitle lines.** The old approach overlapped voice-detection results with the subtitles before cutting, and it dropped 40% of the dialogue lines. [Basis](EXPERIMENTS.md#dialogue-coverage)
- **Voice detection is used only to measure how many seconds the subtitles differ from the audio track.** When `--offset` is given, it does not run at all. No model is used to judge "is someone speaking in this clip" or "is this the character or background voices".
- TV narration and crowd cheers in the subtitles are still put into the clip table. A person labels them "Other" while labeling. There used to be a separate "not speech" label. It was removed when labeling was reduced to target characters and "Other". Such clips go into training as "Other", which teaches the machine that cheers and sound effects are not the target.
- Subtitle lines are not filtered by positioning tags such as `\pos`. In the three episodes, most lines with positioning tags are real dialogue.
- **Episodes 1 and 2 are not re-cut.** Re-cutting would invalidate all 485 manual labels. Clips are added with `extend`, which only adds and never changes existing clips.

**Audio**

- All clips go through the same processing, and the voices of all of them are separated. No clip is picked case by case as "this one is clean, use the original track".
- Analysis uses 16 kHz. Export cuts from the vocal track at the original sample rate. It does not upsample to pretend high frequencies were recovered.
- Do not filter clips by a quality ranking or a quality quota. Small groups are kept, not merged into one leftover group. A quality ranking can guarantee neither identity nor cleanliness.

**Voiceprints and grouping**

- **Clips shorter than 0.5 seconds get no voiceprint and do not take part in grouping** (ranking accuracy 0.61, where chance is 0.50). Clips of 0.5 to 1 second score 0.81, so they are kept for now. [Basis](EXPERIMENTS.md#clip-length)
- **Use the `anime-va` model.** [Basis](EXPERIMENTS.md#episode-3-held-out-test)
- **Each model has its own default threshold, and these cannot be copied from one model to another.** Changing models means sweeping again. The `anime-va` threshold is 0.70. [Basis](EXPERIMENTS.md#switch-to-an-anime-model)
- **The merge rule is average linkage.** [Basis](EXPERIMENTS.md#merge-rules)
- The clips of all episodes are grouped together directly. Each episode is not first squashed into a center point, and the machine's groups are not used as identities.

**Identity and interface**

- **The interface uses a small classifier to assign clips to character names. Grouping is used only at the start, to give a whole group a name.** The three voiceprint models are joined together and fed into a logistic regression. [Basis](EXPERIMENTS.md#classify-by-name). On 2026-10-23 this route was settled. Once seven episodes are labeled, correcting the classifier's mistakes takes much less work than naming groups, so no more numeric comparisons with grouping are planned for it.
- **Only target characters get names. Everyone else is labeled "Other". Each target character gets its own classifier that answers "is this the target?"** Users usually want only one or two characters, and naming every line of every episode is wasted effort. Target characters are added and removed partway through, so each "Other" label records the target characters that existed at that time. From 2026-10-23, the labels for episodes 1 to 3 were migrated to Tokai Teio (label name `teo`) and "Other". The original is archived in `runs/labels/archive-20261023-170304/`. Since the change, only one target character, `teo`, has been measured ([numbers](EXPERIMENTS.md#classify-by-name)).
- **A clip counts as "confident" only if it has a confidence of at least 0.6 and passes the similarity check.** With confidence alone, too few characters get labeled, and narration gets forced into a known character. [Basis](EXPERIMENTS.md#confidence-in-the-interface)
- **Retire "unclear", "multiple people" and "not speech".** When the only question is whether a clip is the target, these labels cannot say whether it is the target. On 2026-10-23, the remaining 102 clips were cleared and sent back for re-listening, rather than being changed straight to "Other". A few of them looked very much like Teio. Most likely Teio was speaking at the same time as someone else. Those should be labeled "target, low quality".
- Train only on labels that a person has confirmed. The machine's predictions are not used for training, and they are not saved as a separate copy to serve as labels.
- **Negative examples are not removed by how easy they are. But clips the machine is confident are "Other" do not need line-by-line checks by a person.** Easy negatives do not help accuracy, and keeping them in training costs almost no time. The real effort is a person confirming them, so a person looks only at the hard ones. [Basis](EXPERIMENTS.md#keep-only-the-hard-negatives)
- **Clips shorter than 1 second that are at least 0.5 seconds away from the dialogue before and after them are skipped by default.** They do not count as work for a person. They are not in the initial grouping or the Characters view, and they are not exported as "confident". In the "Whole episode" view they are hidden by default. Clicking "Show short lines" lists them. If a person has labeled them, the person's label is used. [Basis](EXPERIMENTS.md#short-lines-skipped-by-default)
- Every episode processed must have both video and subtitles. If either is missing, the run is refused. The subtitles decide how to cut, and the video lets a person identify the speaker.
- New labels (the added clips for episodes 1 and 2, and everything from episode 4 on) are made in the correction interface and stored in `runs/labels/`. The blind archives for episodes 1 to 3 remain in `annotations/`. See item 3 under labeling in [HISTORY.md](HISTORY.md#labeling).

**Export**

- **When the subtitles used for cutting are a translation, the dialogue text is taken from a separate original-language subtitle file for each episode.** This is still done without speech-to-text. The offset is measured by comparing the two subtitle files. If the overlap is below 0.6, attaching is refused. Clips that cannot get complete dialogue, or that mix in someone else's speech, are not exported. They are recorded in `rejected.tsv`, and half-matched text is not forced into a clip. [Basis](EXPERIMENTS.md#japanese-dialogue)

## Ruled out

All of these were tried. The data is behind the links. Do not reopen them.

| What was tried | Result |
| --- | --- |
| [Switch to WeSpeaker](EXPERIMENTS.md#62-sampled-labels) | No setting beat `redimnet2-b6`, let alone `anime-va` |
| [Merge by the nearest pair, by the farthest pair, or by mutual nearest neighbors](EXPERIMENTS.md#merge-rules) | All were worse than average linkage |
| [A few identity references](EXPERIMENTS.md#62-sampled-labels) | The gain was limited, and it also spread the wrong people already mixed into the original group |
| [Two-step grouping](EXPERIMENTS.md#two-step-grouping) (group the long clips first, then attach the short clips) | 1057 wrong-merge pairs, against 68 in the control |
| [Score normalization](EXPERIMENTS.md#score-normalization) | Ranking accuracy rose by only 0.0022, and short clips got worse |
| [Padding short clips with the neighboring audio](EXPERIMENTS.md#padding-with-neighboring-audio) | Padding to 1.5 seconds gained only 0.0018. Padding to 3 seconds clearly got worse |
| [Re-cutting short clips along the whole subtitle line](EXPERIMENTS.md#padding-with-neighboring-audio) | A whole line is only about 0.1 seconds longer than the clip. The clips are short because the subtitle lines themselves are short |
| [Filtering out signs and fansub group names with subtitle positioning tags](HISTORY.md#filtering-and-diagnosis) | Drops real dialogue from the main episode |
| Using a model to judge whether anyone is speaking | The old overlap-based cutting did this, and [it dropped 40% of the dialogue lines](EXPERIMENTS.md#dialogue-coverage) |
| Keeping the top half by audio quality ranking | Still let through interjections and sound effects, and also dropped usable clips. The route and its dependencies have been removed |
| Holding out one episode for blind labeling as a held-out test | Cancelled on 2026-10-23. Blind labeling a whole episode takes too much effort. Instead, the machine's mistakes are corrected in the correction interface. The labels made that way are also training data. The evidence stops at [the episode 3 result](EXPERIMENTS.md#classify-by-name) |

The matching commands and options (such as `--method single`) are still there, only so that results can be recomputed. Do not treat them as the current approach.
