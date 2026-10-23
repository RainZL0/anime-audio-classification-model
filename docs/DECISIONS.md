# Settled approaches and ruled-out paths

This page lists only the conclusions. Each one has a one-sentence reason. To overturn one of these, bring new data first, then change it here. Approaches that are not settled yet are not listed here. The questions still being tested are in [STATUS.md](STATUS.md).

## Settled

**Goal and scope**

- The unit of collection is a **character**, not a voice actor. New characters are allowed. Do not force an unknown character into a known name.
- Settle identity classification first. Interjections and noise come later.
- Subtitles give only the time boundaries and the dialogue text. No speech-to-text or text recognition is added.
- Do not fine-tune the voiceprint models. There are only labels for a few episodes, which is not enough. For when to reconsider this, see [ROADMAP.md](ROADMAP.md#direction).

**Cutting clips**

- **Always cut along whole subtitle lines.** Cutting by voice detection instead dropped 40% of the dialogue lines.
- **Voice detection is used only to measure how many seconds the subtitles differ from the audio track.** When `--offset` is given, it does not run at all. No model is used to judge "is someone speaking in this clip" or "is this the character or background voices".
- TV narration and crowd cheers in the subtitles are still put into the clip table. A person labels them "Other". Such clips go into training as "Other", which teaches the machine that cheers and sound effects are not the target.
- Subtitle lines are not filtered by positioning tags such as `\pos`. Most lines with positioning tags are real dialogue.
- **Subtitle files are read by fixed rules, with no AI model and no editing by hand.** The format is fixed; what varies by subtitle group is the text encoding, the style names and the caption marks. All three are worked out from the file itself. The dialogue styles are picked by how widely their lines are spread through the episode and how many there are. Names are not matched against a list of words such as "OP" or "sign", which would differ from group to group and language to language. The person can see the choice and override it.
- **Caption marks are removed by rules kept in one file, and marks the rules do not know are reported, never passed on silently.** No set of rules covers every subtitle maker. The way to handle a file the rules miss is a documented plain subtitle format that any script, editor or AI agent can produce, or a new rule in that one file ([SUBTITLES.md](SUBTITLES.md)). The program does not load code written by the user, which would break when its own code changes.
- Clip IDs depend only on the episode name and the time range, so labels stay valid as long as the clips are not re-cut.

**Audio**

- All clips go through the same processing, and the voices of all of them are separated. No clip is picked case by case as "this one is clean, use the original track".
- Analysis uses 16 kHz. Export cuts from the vocal track at the original sample rate. It does not upsample to pretend high frequencies were recovered.
- Do not filter clips by a quality ranking or a quality quota. A quality ranking can guarantee neither identity nor cleanliness.

**Voiceprints**

- **Clips shorter than 0.5 seconds get no voiceprint.** At that length, telling two characters apart is barely better than a coin toss. Clips of 0.5 to 1 second are still usable, so they are kept.
- **The first groups in the Groups view use the `anime-va` model and average linkage** (merging two groups by the average distance between all their clips). Among the models and merge rules tried, this pair made the fewest wrong merges.
- **Each model has its own similarity scale, so a threshold cannot be copied from one model to another.**

**Identity and interface**

- **The interface uses a small classifier to assign clips to character names. Grouping is used only at the start, to give a whole group a name.** The three voiceprint models are joined together and fed into a logistic regression. In real labeling, correcting the classifier's mistakes takes much less work than naming groups, so no numeric comparison with grouping is planned.
- **Only target characters get names. Everyone else is labeled "Other". Each target character gets its own classifier that answers "is this the target?"** Users usually want only one or two characters, and naming every line of every episode is wasted effort. Target characters are added and removed partway through, so each "Other" label records the target characters that existed at that time.
- **A clip counts as "confident" only if it has a confidence of at least 0.6 and passes the similarity check.** With confidence alone, narration gets forced into a known character.
- **There are no "unclear", "multiple people" or "not speech" labels.** When the only question is whether a clip is the target, these labels cannot say whether it is the target. A target speaking over someone else is labeled "target, low quality".
- Train only on labels that a person has confirmed. The machine's predictions are not used for training, and they are not saved as a separate copy to serve as labels.
- **Negative examples are not removed by how easy they are. But clips the machine is confident are "Other" do not need line-by-line checks by a person.** Easy negatives do not help accuracy, and keeping them in training costs almost no time. The real effort is a person confirming them, so a person looks only at the hard ones.
- **Clips shorter than 1 second that are at least 0.5 seconds away from the dialogue before and after them are skipped by default.** They are almost never the lines people want. They do not count as work for a person. They are not in the initial grouping or the Characters view, and they are not exported as "confident". In the Scenes view they are hidden by default. Clicking "Show short lines" lists them. If a person has labeled them, the person's label is used.
- Every episode processed must have both video and subtitles. If either is missing, the run is refused. The subtitles decide how to cut, and the video lets a person identify the speaker.
- Labels are made in the interface and stored in the workspace's `labels/` folder.

**Export**

- **When the subtitles used for cutting are a translation, the dialogue text is taken from a separate original-language subtitle file for each episode.** This is still done without speech-to-text. The offset is measured by comparing the two subtitle files. If the overlap is below 0.6, attaching is refused. Clips that cannot get complete dialogue, or that mix in someone else's speech, are not exported. They are recorded in `rejected.tsv`, and half-matched text is not forced into a clip.

## Ruled out

All of these were tried. Do not reopen them.

| What was tried | Result |
| --- | --- |
| Switching to the WeSpeaker model | No setting beat `redimnet2-b6`, let alone `anime-va` |
| Merging groups by the nearest pair, by the farthest pair, or by mutual nearest neighbors | All were worse than average linkage |
| Grouping around a few known example clips per character | The gain was small, and wrong clips already in a group spread further |
| Two-step grouping (group the long clips first, then attach the short clips) | Far more wrong merges |
| Score normalization (rescaling similarities by how close each clip is to everything else) | Almost no gain, and short clips got worse |
| Padding short clips with the neighboring audio | Little gain at 1.5 seconds, clearly worse at 3 seconds |
| Filtering out signs and fansub group names with subtitle positioning tags | Drops real dialogue |
| Cleaning caption marks with an existing tool (Subtitle Edit, subtitle-filter), checked 2026-10 | They only know half-width brackets and English habits, and they throw away speaker names, which export needs |
| Using a model to judge whether anyone is speaking | Dropped 40% of the dialogue lines |
| Keeping the top half by audio quality ranking | Still let through interjections and sound effects, and also dropped usable clips |
| Holding out one episode for blind labeling as a test | Blind labeling a whole episode takes too much effort. The machine's mistakes are corrected in the interface instead, and those labels are also training data |
