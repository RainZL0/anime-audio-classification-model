# Rules and lessons

This page holds the working rules. Each rule was set after a mistake, and the mistake is noted next to it. Technical choices, such as which model or which cutting method to use, are in [DECISIONS.md](DECISIONS.md). Experiment numbers are in [EXPERIMENTS.md](EXPERIMENTS.md).

| Section | What it covers |
| --- | --- |
| [Scoring](#scoring) | Which numbers count as valid |
| [Tuning parameters](#tuning-parameters) | Mistakes to avoid when tuning the threshold or changing approach |
| [Filtering and diagnosis](#filtering-and-diagnosis) | Before adding a filter or drawing a conclusion |
| [Labeling](#labeling) | How manual labels become ground truth |
| [Keeping and deleting](#keeping-and-deleting) | What must not be deleted, and what has been deleted |

## Scoring

1. **Ground truth is only the names confirmed by checking the picture.** If you give a machine-made group a majority label and then score against that label, you hide the wrong people mixed into the group. Labels made by one model cannot be used to verify that same model.
2. **Reference clips that are used to give the algorithm identities must be excluded from scoring.** The baseline must exclude the same clips. Remaining labels that were already used to try a method still do not count as a held-out test.
3. **Labels cannot be carried over when the clip boundaries differ.** Once an old, large identity span was applied to new, smaller clips, which inflated the scoring coverage.
4. **Wrong merges and missed merges must be reported together.** Putting every clip in its own group also gives zero wrong merges. Check the number of groups as well, and how many clips still have no manual name.
5. **When a sample is so small that a count is 0, the 0 describes the sample, not the system.** "Zero wrong merges" on 62 labels, against 68 pairs on 445 labels. The basis for "the missed merges are all short clips" is only 31 pairs.
6. **Tuning and scoring on the same labels hides problems. Only a different batch of labels reveals them.** The two-step grouping approach gave zero wrong merges on the old labels, with 19 more linked pairs. On the full set of labels it added 989 wrong-merge pairs.
7. **The gain seen while tuning shrinks.** `anime-va` added 504 linked pairs on the first two episodes, but only 9 on the held-out test. Switching models was the right decision, but do not trust the size of the gain seen during tuning.
8. **Fix the scoring rule for the held-out test before labeling.** After episode 3 was labeled, `anime-va` gave very different results under two rules. The rule agreed in advance showed 9 more linked pairs. The rule swapped in afterwards showed 711. Fixing the rule first leaves no room to pick whichever one suits you.
9. **Pairs are not independent observations.** One character with many clips creates many pairs. After the reference changed, the scoring set changed too. So a drop in "the number of missed merges" cannot be taken directly as an improvement.
10. **Fix the clips first, then compare the grouping, and only then compare changes to the cutting on their own.** Do not change clip boundaries in the same comparison.
11. **Nearest-neighbor search leaves out the query clip itself.** A character with only one label is not used as a question, but it stays in the candidate pool as background. A nearest neighbor without a name is only a clue. It cannot be counted as a wrong person.

## Tuning parameters

1. **When merging by average group distance, the global threshold is not a constant.** As the pool grows, it becomes harder for a group's average distance to pass the threshold. So the same threshold merges more conservatively. On a corpus that keeps growing, "tune one threshold" is itself an answer that goes stale. [Basis](EXPERIMENTS.md#threshold-drift)
2. **If two numbers move in the same direction, the threshold is probably just in the wrong place. Only when they move in opposite directions is things getting worse.** As the pool grows, with a fixed threshold, both linked pairs and wrong merges go down. If you hold wrong merges still and move the threshold again, the linked count does not drop at all, and it even rises. Judging only by the drop in linked pairs, and concluding that a bigger corpus is harmful, sends you to fix a problem that does not exist.
3. **Similarity scales differ between models.** A threshold copied from one model sweeps a meaningless range. The `--low` and `--high` options of `compare` must be set for each model.
4. **Do not jump from a result to its root cause.** Changing models or reference methods without an improvement does not prove that the voiceprint step is fine. Diagnose first, then decide which step to change. Do not take turns trying models and thresholds.
5. **Centers lock in upstream mistakes.** Once, a group with the wrong people mixed in was averaged into a center point, and the clip-level threshold was then moved onto the center points. This caused many wrong merges.
6. **Correct nearest-neighbor search does not mean nearest neighbors can be linked into groups.** The nearest labeled clip of a labeled clip is almost always the same character. But across the whole pool, the nearest clips are mostly unnamed. Merging by the nearest pair goes through them and chains characters into one big cluster.

## Filtering and diagnosis

1. **Count before you add a filter.** At one point the idea was to filter out signs and fansub group names using subtitle positioning tags (`\pos`). When counted, most dialogue lines with positioning tags in the three episodes turned out to be real dialogue.
2. **Ordinary noise reduction is not the same as identifying and removing another character's voice.** Karaoke-style separation also does not split by person. Both the lead vocal and the backing vocals can contain several people, so it cannot be used to extract the target speaker.
3. **Check "boundary anomalies" by actually listening.** "No overlap" on the speech timeline only means the labels do not overlap. Another person may still be speaking in the audio.
4. **Subtitles have always been a usable input.** Once, they were wrongly recorded as missing, and a detour was taken because of it.

## Labeling

1. **Groups made by ear from memory are not usable ground truth.** In the early period, nearly half of the groups made by ear were unclear. Only names reported after checking the picture give usable identities. The old field records are kept in `annotations/legacy/`, but the ear-based group numbers are not upgraded to ground truth.
2. **Listening to old labels is used only to help the labeler remember who a name is.** Judgment still rests on the picture. If similarity is judged by ear, the labels become groups made by a person. But they were meant to test the machine's grouping.
3. **Episodes 1 to 3 are blind-labeled. The labeling page shows no machine groups, group numbers or candidate assignments.** They are stored in `annotations/`. From 2026-10-23, the held-out test was cancelled. New labels (clips added for episodes 1 and 2, and everything from episode 4 on) are made in the correction interface and stored in the workspace's `labels/`. They are used both for training and for scoring. There is only one labeler. Even after seeing the predictions, identities still come from checking the picture.
4. **In each episode, a character must always have the same name.** Episode 1's label "Red Hair" and episode 2's "Nice Nature" were once treated as two people. As a result, one correct merge was recorded as a wrong merge. Before labeling a new episode, check against `annotations/names.json` and the previous episode's archive.
5. **Label a whole episode in one pass, not a sample.** Labeling a sample means finding each picture again every time. Most of the effort then goes into finding the spot rather than identifying the speaker, and the coverage is incomplete.

## Keeping and deleting

**Original material, manual records made by checking pictures, working models and expensive caches must be kept.** Check references and migrations before deleting anything.

Cleanups done so far:

- 2026-09-06: deleted the old experiment folders, interim groupings, old exports, and the karaoke model, which was unsuitable for dialogue. 1071 files in total, about 1.88 GB. Each path is recorded in `runs/cleanup.json`.
- 2026-09-06: at the labeler's request, deleted 62 sampled labels (`annotations/ep01_v4.json`, `ep02.json`). Before deleting, the 27 character names that were used were pulled into `annotations/names.json`. The file contents are still in the git history (`git show b37ef47:annotations/ep01_v4.json`), but the numbers these labels supported can no longer be recomputed.
- 2026-09-07: moved the superseded reports under `runs/` into `runs/superseded/`. The reason is in the `README.txt` there.

The lessons from the previous repo, `anime-audio-classification-model`, have been absorbed into this file and [DECISIONS.md](DECISIONS.md), and are no longer maintained separately. Those lessons were: averaging MFCC features threw away pitch and rhythm; there was no preprocessing at all; it was built as a closed binary classification; and scoring had no independent split, with a test set that had no labels.
