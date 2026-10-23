# Experiments done

This page records only finished experiments and their numbers. It has no plans and no rules. For the terms, see the [glossary](HOW_IT_WORKS.md#glossary). The approaches settled by these experiments are summarized in [DECISIONS.md](DECISIONS.md).

**Read in two periods.** Before 2026-09-06 the work used 62 sampled labels. Those labels were deleted at the labeler's request, and only the lessons are kept, in [the last section](#62-sampled-labels). After that came full labeling of three episodes: 860 of the 1184 clips have a person's name. That is the valid evidence.

| Section | One-line conclusion |
| --- | --- |
| [Classify by name](#classify-by-name) | With manual labels, clips can be assigned to character names directly. The most confident 80% of clips are 0.97 correct, which is worth pursuing |
| [Keep only the hard negatives](#keep-only-the-hard-negatives) | When scoring only `teo` vs "Other", cutting the negatives down to the hardest 10% makes almost no difference. Easy negatives do not help, but they do not hurt either |
| [Confidence in the interface](#confidence-in-the-interface) | Adding the similarity check raises the accuracy of confident clips from 91.7% to 98.6%. Narration and passers-by are no longer forced into a name |
| [Episode 3 held-out test](#episode-3-held-out-test) | Switching to `anime-va` was right. It wins by making fewer mistakes, not by linking more pairs |
| [Clip length](#clip-length) | Under 0.5 seconds is basically useless. 0.5 to 1 second is weak |
| [Short lines skipped by default](#short-lines-skipped-by-default) | Subtitles almost never cut a long line into short pieces. But judging only by timing, the rule saves just 44 lines across three episodes |
| [Japanese dialogue](#japanese-dialogue) | Attaching Japanese subtitles to clips by time works: 132 of Teio's 171 clips got text. Fine-tuning on that data makes the voice sound closer |
| [Threshold drift](#threshold-drift) | As the pool grows, the fixed threshold slides. It is not the scores that fall. A threshold set from the pool keeps things stable |
| [Switch to an anime model](#switch-to-an-anime-model) | The only change that really worked. The variant trained by voice actor is the best |
| [Dialogue coverage](#dialogue-coverage) | The old cutting lost 40% of the dialogue. Cutting along every subtitle line covers all of it |
| [Score normalization](#score-normalization) | Did not work |
| [Padding with neighboring audio](#padding-with-neighboring-audio) | Did not work |
| [Two-step grouping](#two-step-grouping) | More than ten times the wrong merges. Rejected |
| [Merge rules](#merge-rules) | Average linkage is the best |
| [62 sampled labels](#62-sampled-labels) | Lessons only. WeSpeaker and a few identity references were ruled out in this period |
| [Limits of the evidence](#limits-of-the-evidence) | Where these conclusions cannot yet be generalized |

## Classify by name

2026-10-18. Trained on the 445 manual labels of episodes 1 and 2, the clips of episode 3 are assigned directly to character names, and scored on episode 3 only. Episode 3 has 303 clips that have a person's name and a voiceprint. Nine of them (7 of Matikanetannhauser and 2 of Matikanefukukitaru) belong to characters that are not in the training set. They are necessarily wrong, so the highest possible accuracy on all clips is 0.970. Episode 3 was used earlier to choose `anime-va`. **This is not a held-out test. It is used only to judge whether the direction is worth pursuing.**

Three methods:

- Closest single clip: takes the name of the most similar labeled clip in the training set. This is the clip-to-clip comparison that grouping relies on.
- Character average: assigns the character whose average direction is closest.
- Small classifier: a logistic regression (a simple model that outputs a probability for each class). Its regularization strength (a setting that keeps the model from fitting noise too closely) was picked by holding out episodes 1 and 2 in turn.

"The most confident 80%" means sorting the predictions from most to least confident and looking only at the top 80% of the clips. Those clips could be accepted directly, and the rest handed to a person to confirm.

| Voiceprint | Closest single clip: all / top 80% most confident | Character average | Small classifier |
| --- | ---: | ---: | ---: |
| anime-va | 0.782 / 0.881 | 0.809 / 0.926 | 0.802 / 0.918 |
| anime-char | 0.782 / 0.860 | 0.792 / 0.922 | 0.822 / 0.934 |
| redimnet2-b6 | 0.786 / 0.897 | 0.805 / 0.897 | 0.832 / 0.963 |
| All three joined together | 0.828 / 0.938 | 0.845 / 0.959 | **0.852 / 0.971** |

With all three joined together, the small classifier's accuracy by clip length: 0.5 to 1 second 0.714 (35 clips), 1 to 1.5 seconds 0.857 (70 clips), 1.5 to 3 seconds 0.880 (142 clips), 3 to 6 seconds 0.857 (56 clips).

The 45 errors of the small classifier (all three joined):

- 15 are "passers-by". That label covers a group of minor characters who share one name. It is not one person's voice, so learning it as a single character was never going to work well.
- 9 are characters that are not in the training set.
- Of the remaining 21, 9 were assigned to `teo`. `teo` has 112 clips in the training set, far more than any other character. Characters with only 1 to 7 training clips (Satono Diamond, Kitasan Black, Twin Turbo) are easily pulled into it.

After removing "passers-by", 268 clips remain. The small classifier's overall accuracy is 0.888, and its top 80% most confident clips are 1.000 correct. This comparison was done afterwards. It is only used to show that "passers-by" should be a special label that is not used in training.

**How to read these numbers:**

- With a person's name in hand, even the simplest "closest single clip" can give a character name directly. Grouping cannot do that. It only gives a group number, and a person still has to name each group.
- Compared with "closest single clip", the small classifier raises the overall accuracy by 2 to 5 percentage points, and the top 80% by 3 to 7 points. One clip out of 303 is 0.33 percentage points. So methods within a point or two of each other on the same row cannot be told apart.
- Joining the three models beats any single one. And `redimnet2-b6`, trained only on general speech (VoxCeleb2), is no worse than the two anime-domain models.
- The regularization strengths picked between episodes 1 and 2 all landed at the high end of the candidate range (100 to 1000). That means the constraint is set very loosely.
- The 3 to 6 second band is no better than 1.5 to 3 seconds. Its errors are mostly "passers-by" and characters with few training clips, not short clips.

Report: `runs/classify/ep03-*.json`. Each report has per-clip predictions, so you can listen back to them.

**Scoring only `teo` vs "Other"** (2026-10-23, labels from the interface. Episodes 1 to 3 are each held out in turn, and the rest are used for training. `teo` has 230 clips in total. Special labels and "low quality" are not counted):

| Voiceprint | Ranking accuracy | Wrongly accepted at 0.6 | Missed at 0.6 | Ranking accuracy under 1 second |
| --- | ---: | ---: | ---: | ---: |
| anime-va | 0.9895 | 7 | 25 | 0.994 |
| anime-char | 0.9971 | 3 | 17 | 0.997 |
| redimnet2-b6 | 0.9933 | 9 | 21 | 0.969 |
| All three joined together | **0.9992** | **0** | **13** | **1.000** |

Joining all three is still best. Wrong accepts drop from 3 to 9 clips down to 0. The three voiceprints took only about 37 seconds on episode 4 in total (including loading the models), while voice separation takes about 13 minutes. So computing two extra models is not the bottleneck.

## Keep only the hard negatives

2026-10-23. The question: most of the "Other" labels in the interface are clearly not Teio at a glance. Is it enough to keep only the hard negatives (the ones the machine thinks are most like Teio)? Method: using the interface's labels, score only `teo` vs "Other" (special labels and "low quality" not counted). Hold out one of episodes 1 to 3 in turn and score it, training on the rest (including the labeled clips of episode 4). Keep all the positives. Keep only part of the negatives, ranked by the full model's probability of Teio from high to low, or keep the same number at random as a control. Averaged over the three episodes, `teo` has 230 clips in total:

| Negatives kept | Count | Ranking accuracy | Wrongly accepted at 0.6 | Missed at 0.6 |
| --- | ---: | ---: | ---: | ---: |
| All | about 507 | 0.9992 | 0 | 13 |
| Hardest half | about 253 | 0.9992 | 0 | 13 |
| Hardest quarter | about 126 | 0.9991 | 0 | 10 |
| Hardest 10% | about 50 | 0.9986 | 1 | 7 |
| Random 10% | about 50 | 0.9977 | 43 | 3 |

- Removing easy negatives hardly changes the result. What matters is which ones are kept, not how many. With the same 50 clips, random keeping wrongly accepts 43, while picking the hard ones wrongly accepts only 1.
- It does not hurt either. Logistic regression hardly adjusts to samples it already gets right. Training on about a thousand clips takes under a second, so removing them saves little.
- Teio is already well separated from the others (ranking accuracy 0.999). Whether the same holds for target characters with similar voices has not been measured. "Hardest" was picked with the full model. The interface can only use the previous round's model to pick.

## Confidence in the interface

2026-10-18. When only two characters are labeled in the interface, narration was read as `teo` with 67% confidence. The small classifier can only pick among the characters it knows. So a [similarity check](HOW_IT_WORKS.md#labeling-and-correction-interface) was added. The same split as in the previous section measures its effect: train on the labels of episodes 1 and 2, leave out the passers-by, and evaluate on episode 3. Episode 3 is again not a held-out test.

| Condition for "confident" | Share of clips that are confident | Of those, correct |
| --- | ---: | ---: |
| Confidence at least 0.6 | 79.9% | 91.7% |
| Confidence at least 0.6, and passes the similarity check | 68.3% | 98.6% |

- Among clips that fail the similarity check, the small classifier got only 35.7% right. So handing them to a person is the right call.
- Of the 35 passers-by, only 2 were counted as confident.
- The cost: the clips a person has to check rise from about 20% to about 30%.

## Episode 3 held-out test

All 375 clips of episode 3 are labeled (306 with names, 69 with special labels, 19 characters). This is the first data in the project that took no part in tuning at all. **The scoring rule was fixed before labeling.** All three episodes are grouped together, and only the pairs from episode 3 are scored. This way the threshold comes from episodes 1 and 2, and every pair scored is new.

The rule agreed in advance:

| Model | Threshold | Linked | Wrong merges | Missed merges | Linked share |
| --- | ---: | ---: | ---: | ---: | ---: |
| redimnet2-b6 | 0.50 | 2082 | 63 | 3182 | 39.6% |
| anime-va | 0.70 | 2091 | **25** | 3173 | 39.7% |

On episodes 1 and 2, `anime-va` linked 504 more pairs. On the held-out test it links only 9 more, and the gap in linked share shrank from 4.8 percentage points to 0.2. What did come true is the other half: wrong merges fell from 63 to 25, a cut of 60%.

**Under a different rule, it wins by a landslide.** Episode 3 alone as the pool, with the threshold swept. This is an explanatory comparison done afterwards, not one agreed in advance:

| Wrong-merge limit | redimnet2-b6, most linked | anime-va, most linked |
| ---: | ---: | ---: |
| 25 or fewer | 1376 @0.42 | **2105** @0.67 |
| 63 or fewer | 1766 @0.46 | **2477** @0.69 |
| 120 or fewer | 1919 @0.49 | **3259** @0.77 |
| 250 or fewer | 2437 @0.55 | **3423** @0.79 |

Both rules support switching models, but by very different margins. Trust the rule agreed in advance: `anime-va` is better, but because it makes fewer mistakes, not because it links more pairs.

After dropping clips shorter than 0.5 seconds, `anime-va` on episode 3 gives 2095 linked, 21 wrong merges and 3169 missed merges.

Reports: `runs/groups/blind-*.json`, `runs/comparison-ep03.json`, `runs/score-ep03.json`.

## Clip length

Episode 3 is the first labeling with clips under 1 second, so this question can finally be measured:

| Shorter clip in the pair | Same-character pairs | redimnet2-b6 ranking accuracy / error rate | anime-va ranking accuracy / error rate |
| --- | ---: | ---: | ---: |
| 0 to 0.5 seconds | 130 | 0.6113 / 0.415 | 0.5500 / 0.478 |
| 0.5 to 1 second | 1105 | 0.8068 / 0.271 | 0.8252 / 0.257 |
| 1 to 1.5 seconds | 1791 | 0.8989 / 0.177 | 0.8725 / 0.206 |
| 1.5 to 3 seconds | 2015 | 0.8975 / 0.184 | 0.9032 / 0.161 |
| 3 to 6 seconds | 223 | 0.9590 / 0.081 | 0.9502 / 0.081 |

The 0 to 0.5 second band has a ranking accuracy of 0.61. Pure chance is 0.50, so this band is essentially useless. Dropping it lowers episode 3's wrong merges from 25 to 21, and linked pairs even rise by 4. The 0.5 to 1 second band gives 0.81. That is weak, but it is kept for now.

**This corrects an old conclusion.** Earlier it was written that "short clips are not the main problem". That was based on data whose shortest clip was 1.0 second, so the cliff below 1 second could not be seen. The statement still holds for clips over 1 second: even 3 to 6 seconds only reaches 0.96, with an error rate of 0.081. Making all the clips longer does not solve the problem.

## Short lines skipped by default

2026-10-23. The question: short lines under 1 second are of little use for training speech synthesis, so can they go unlabeled? Also: could a long line have been cut by the subtitles into several pieces, each shorter than 1 second?

**In episode 3 (fully labeled), almost no long lines are cut into pieces.** Of the 36 named clips under 1 second (not counting "unclear", "multiple" and "passers-by"), only 4 sit within 0.5 seconds of another clip of the same character. Widening that to 1 second gives only 6. No character has several consecutive clips that are all under 1 second. This matches [padding with neighboring audio](#padding-with-neighboring-audio), where the short clips turned out to be short because the subtitle line itself is short.

**But the interface cannot tell who is speaking, so it can only look at timing.** The rule: skip a clip if it is under 1 second and at least 0.5 seconds away from every other line before and after it (other clips, or subtitle lines with no clip). Dialogue is dense. Most short lines have someone else speaking within 0.5 seconds before or after:

| Gap between the short line and the nearest other line | Count (three episodes) |
| --- | ---: |
| Overlapping or touching | 37 |
| 0 to 0.3 seconds | 81 |
| 0.3 to 0.5 seconds | 22 |
| 0.5 seconds or more, or no other line within 20 seconds | 45 |

Of the 185 short lines across the three episodes, only 44 are skipped (12, 20 and 12 per episode). One more sits exactly 0.5 seconds away and is kept under the rule. So the saving is less than a quarter of the labeling. Of the 12 skipped in episode 3, 6 are Tokai Teio. Of the 42 kept, only the 4 described above sit next to the same character. The rest sit next to other people's lines. To save more, you would need to use voiceprints to decide whether the lines before and after are the same person. That has not been done.

## Japanese dialogue

2026-10-23. Clips were cut along the Chinese subtitles, but training a Japanese model needs the Japanese original text. The question: can a separate Japanese subtitle file be used to give the clips their text by time, and is the result useful for training GPT-SoVITS? The Japanese subtitles come from the kitsunekko mirror. There are four sources: Netflix, Amazon, TX and NanakoRaws. They are stored in `data/subtitles/uma_s2/ja/`.

**The offset can be measured, and a wrong file can be caught.** The overlap score is the intersection of the two subtitle files' display times divided by their union. Japanese subtitles split lines differently from Chinese ones, so even a correct match never reaches 1:

| Japanese subtitles | Episode 1 | Episode 2 | Episode 3 |
| --- | ---: | ---: | ---: |
| Netflix | 0.78 | 0.72 | 0.73 |
| Amazon | 0.78 | 0.78 | 0.77 |
| TX | 0.70 | 0.69 | 0.69 |
| NanakoRaws | 0.68 | 0.67 | 0.69 |
| Wrong file: the next episode's Netflix | 0.51 | 0.49 | 0.50 |

The rejection line is set at 0.6. The measured Netflix offset is −0.93 to −0.94 seconds, almost the same as the Chinese subtitles' own offset of −0.95 seconds. Another check, "how many clips touch a dialogue line", gives over 99% for the right file and 83% to 88% for the wrong one. So it only catches obvious errors.

**Only keep a clip if every line falls inside it.** Japanese subtitles often stay on screen a little longer than the speech. A line that extends less than 0.8 seconds at either end is still kept. Extending further means the line is only partly spoken. Netflix subtitles tag off-screen narration with names, and one subtitle entry often holds two people each saying one line. So entries are split into lines, and a clip is dropped if a line with someone else's name overlaps it by more than 0.2 seconds. Results for the 171 Teio clips confirmed by a person (Netflix subtitles):

| Result | Count |
| --- | ---: |
| Text attached | 132 (4.2 minutes) |
| One line only partly matches | 32 |
| Someone else's speech in the line | 5 |
| No matching dialogue | 2 |

**Training helps.** After also dropping clips shorter than 1 second, longer than 12 seconds, or overlapping other clips, 118 remain (4.0 minutes). GPT-SoVITS v2ProPlus was fine-tuned on them (SoVITS 8 rounds, GPT 15 rounds, official default settings). The same reference audio was used to synthesize 4 lines that were not in training. Each synthesized line was compared with Teio's average voiceprint from the human labels, using cosine similarity (a score of how alike two voiceprints point). The `anime-va` voiceprint was used. The reference audio itself scores 0.767:

| Line | Not fine-tuned | After fine-tuning |
| --- | ---: | ---: |
| トレーナー、今日もボクと一緒に走ろうよ！ | 0.505 | 0.566 |
| えへへ、カイチョーに褒められちゃった。 | 0.463 | 0.518 |
| 無敗の三冠ウマ娘になるのは… | 0.614 | 0.702 |
| もう、なんでわかってくれないのさ。 | 0.494 | 0.609 |

All four lines score closer after fine-tuning, and they also pull further away from the most similar other character. Pronunciation and tone have not been checked by ear, so there is no conclusion on those points.

**Data grew to 10.7 minutes. It is still improving, but by less.** On the evening of 2026-10-23, the 503 clips of episodes 1 to 7 were filtered by the same rules (also removing clips marked low quality). 302 remain (10.7 minutes), and the same settings trained `teio7`. The same reference audio was used to synthesize 8 lines not in training: the 4 above, plus one each for excited, down, smug and determined. The average voiceprint is now taken from the manual labels of all seven episodes, excluding low quality. So the old version's numbers differ slightly from the table above:

| | Average similarity over 8 lines | Gain over the previous version |
| --- | ---: | ---: |
| Not fine-tuned | 0.538 | |
| `teio` (4.0 minutes, episodes 1 to 3) | 0.615 | 0.077 |
| `teio7` (10.7 minutes, episodes 1 to 7) | 0.646 | 0.031 |

`teio7` beats `teio` on 6 of the 8 lines. The other 2 (the 無敗の三冠… line and the down line) trail by less than 0.01. The reference audio itself scores 0.768. This score measures only the timbre. Tone and pronunciation must be judged by ear. The listening page is at `out/sovits-teio/samples-teio7/index.html`.

**GPT-SoVITS V5 without fine-tuning ties with the fine-tuned `teio7`.** The V5 turbo base model, released 2026-10-05 (4 steps, no CFG, a sampling setting; the GPT part is still `s1v3.ckpt`), was used to synthesize the same 8 lines directly. With only the reference audio above, V5 averages 0.663, which is 0.017 higher than `teio7`. Then 4 more reference clips with different emotions were tried (all `teo` clips confirmed by a person). Each side wins some:

| Reference audio | Reference itself | `teio7`, 8-line average | V5 turbo, 8-line average |
| --- | ---: | ---: | ---: |
| Confident (episode 1, 13:54, the clip above) | 0.768 | 0.646 | 0.663 |
| Cheerful (episode 1, 1:56) | 0.610 | 0.503 | 0.595 |
| Flustered (episode 5, 19:05) | 0.603 | 0.589 | 0.481 |
| Down (episode 6, 0:59) | 0.670 | 0.598 | 0.601 |
| Relaxed and playful (episode 7, 7:01) | 0.591 | 0.630 | 0.560 |
| Total of 40 lines | | 0.593, standard deviation 0.070 | 0.580, standard deviation 0.080 |

Of the 40 pairs, `teio7` wins 19. V5's scores roughly follow the reference audio itself, and the flustered clip drops the most. `teio7` scores even higher than its reference on the playful clip, but is lowest on the cheerful one, and the cause has not been checked. This measure is the average voiceprint of Teio's confirmed clips, which `teio7` was trained on, so it may favor `teio7`. The listening page is at `out/sovits-teio/refs4/index.html`, and the scores are in `out/sovits-teio/refs4-scores.csv`.

**More training rounds do not move this measure much.** Using `teio7` weights saved partway through training, with the same 5 reference clips and 8 lines:

| SoVITS rounds | GPT rounds | 40-line average |
| ---: | ---: | ---: |
| 4 | 15 | 0.579 |
| 8 | 5 | 0.605 |
| 8 | 15 (that is, `teio7`) | 0.593 |

SoVITS from 4 to 8 rounds gained 0.014. GPT from 5 to 15 rounds actually dropped 0.012. Both changes are around 0.01, which is small next to the difference a change of reference audio makes. Real recordings do not score very high on this measure either. The 415 clips of `teo` that are confirmed and not low quality average 0.532 similarity to the average voiceprint. The 2 to 3 second clips average 0.598, and those over 3 seconds average 0.665. The 8 synthesized lines are mostly 2.5 to 5 seconds long, and 0.58 to 0.61 is already close to real recordings of the same length. To tell good from bad at this level, a different measure is needed. Options include speech recognition to check whether the pronunciation is right, or listening by a person.

## Threshold drift

At first there were only two data points:

| Model @ threshold | Episode 3 only, 375 clips | Episodes 1 to 3 together, 1184 clips |
| --- | ---: | ---: |
| redimnet2-b6 @0.50 | linked 2059 / wrong merges 146 | linked 2082 / wrong merges 63 |
| anime-va @0.70 | linked 2613 / wrong merges 80 | linked 2091 / wrong merges 25 |

The larger the pool, the more conservative the merging gets. Average-linkage merging requires the average distance between all the clips of two groups to pass the threshold. Once a group is large, its average goes up.

`avs drift` fills in the middle. **The scored episode always stays in the pool in full, and only clips from other episodes are added.** It uses nine stages, with 8 random draws at each stage. This way each stage faces the same labels and the same pairs, so the scores can be compared directly. Reports: `runs/drift-ep01.json`, `drift-ep02.json` and `drift-ep03.json`.

### Both numbers fall together at a fixed threshold

Episode 3, with 306 labeled clips and 19 characters. `anime-va` with a fixed 0.70:

| Pool size | Linked | Wrong merges |
| ---: | ---: | ---: |
| 372 | 2613 | 76 |
| 573 | 2382 | 43 |
| 774 | 2160 | 33 |
| 975 | 2215 | 31 |
| 1176 | 2095 | 21 |

Linked pairs fell by 20%, and wrong merges fell by 70%. **When both numbers go down together, the grouping has not gotten worse. The same threshold is sliding toward the conservative end of its own trade-off curve.** The other two episodes show the same pattern. Episode 1 goes from 1128/44 to 1123/11, and episode 2 from 1979/17 to 1683/12.

### Holding wrong merges fixed, linked pairs rise instead

For each pool size, let the threshold move freely, but require wrong merges to stay no higher than what the fixed 0.70 produced on the smallest pool:

| Pool | Episode 3, wrong merges ≤76 | Episode 2, wrong merges ≤17 | Episode 1, wrong merges ≤44 |
| ---: | ---: | ---: | ---: |
| Smallest pool | 2613 @0.700 | 2073 @0.720 | 1128 @0.700 |
| Middle pool | 2932 @0.749 | 2696 @0.765 | 1136 @0.695 |
| Largest pool, 1176 | **3278** @0.780 | 2373 @0.760 | 1123 @0.700 |

No stage got worse. **The trade-off curve that can be reached does not decline as the pool grows. What declines is where a fixed number happens to sit on the curve.** So this is a calibration problem, not "a bigger corpus is no good".

To keep the position, the threshold has to move outward as the pool grows, by 0.00 to 0.08. That is 4% to 11%. The move narrows as the pool grows. Episode 1 needs almost no move, and episode 3 needs the most.

### Setting the threshold from the pool

What is needed is a quantity that can be computed from the pool alone, without manual labels, and that rises by 4% to 11% as the pool grows. Several were tried:

| Quantity computed from the pool alone | 372 clips → 1176 clips |
| --- | ---: |
| 1st percentile of all pair distances | +8.2% |
| 5th percentile of all pair distances | +1.8% |
| Median of all pair distances | +0.3% |
| Median of each clip's distance to its nearest neighbor | −2.6% |
| Median merge height in hierarchical clustering | −2.7% |
| Ratio of groups to clips held fixed | threshold shrinks back |

Only the **1st percentile** has both the right direction and the right size. The reason makes sense. Most pairs in a pool are different characters, so high percentiles such as the median are almost entirely set by them, and they do not move as the pool grows. The few pairs that are very close are mostly same-character pairs. As the pool gets more characters, these pairs become more spread out, so this distance moves outward. The other directions are wrong or hardly move, so they need not be tried again.

So the rule is: **threshold = multiplier × the 1st percentile of all pair distances in the pool**. For `anime-va`, the multiplier is set at 1.275. On the current pool of 1176 clips from three episodes, that gives exactly 0.70. On episode 3, the two approaches side by side:

| Pool size | Fixed 0.70: linked / wrong merges | Threshold from the pool: threshold → linked / wrong merges |
| ---: | ---: | ---: |
| 372 | 2613 / 76 | 0.6465 → 1950 / 18 |
| 573 | 2382 / 43 | 0.6878 → 2131 / 25 |
| 774 | 2160 / 33 | 0.6917 → 2132 / 31 |
| 975 | 2215 / 31 | 0.6993 → 2221 / 31 |
| 1176 | 2095 / 21 | 0.6999 → 2095 / 21 |

The fixed line slides from 2613/76 down to 2095/21. The pool-based line stays nearly still, between 1950/18 and 2221/31. Episode 2 is similar: 1697/11 to 1683/12, while the fixed line falls from 1979/17 to 1683/12. Episode 1 hardly drifted in the first place, so the two lines are the same and neither got worse.

**The multiplier sets how strict the threshold is. That is a separate question from stability.** A multiplier of 1.38 (which gave 0.70 on the 372 clips of episode 3 alone) is equally stable. But that position is much looser. On episode 3, linked pairs rise from 2095 to 3075, while on episode 1 wrong merges rise from 11 to 155. Wrong merges are the more costly error, so the conservative 1.275 was chosen. **Today this rule makes exactly the same groups as the fixed 0.70.** The group membership of all 1184 clips was checked. The two only split once the corpus keeps growing.

### Not yet solved

- The multiplier and the percentile were chosen on the labels of only three episodes. There has been no held-out test.
- Only shrinking back was checked, not pushing outward. The rule was matched between 372 and 1176 clips. There is no data for the range of 13 episodes, about 5,000 clips.
- The clips added to the pool were drawn at random from the other two episodes, with the same character mix as the original episode. What the 1st percentile does when whole episodes with new characters are added is known only from the single real point at 1176 clips.
- Episode 2's curve is not monotonic. It is highest at the 981-clip stage and then drops again at 1176. Episode 1 barely drifts. **The three episodes differ quite a lot, so do not take episode 3's shape as the general rule.**

## Switch to an anime model

Every earlier attempt kept the same model, and all of them failed. This time the model was changed to [anime_speaker_embedding](https://github.com/litagin02/anime_speaker_embedding), which has two variants: `anime-char`, trained by character, and `anime-va`, trained by voice actor. For what the model is, see [TOOLS.md](TOOLS.md). The original two models were trained on VoxCeleb, whose material is mostly interviews with real people, mainly in English.

Episodes 1 and 2: 809 clips, 445 labels and 98790 pairs, with the same code:

| Model | Ranking accuracy | Equal error rate | 1 to 1.5 seconds | 1.5 to 3 seconds | 3 to 6 seconds | Across episodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| redimnet2-b6 (the original) | 0.9296 | 0.1412 | 0.9239 | 0.9430 | 0.9402 | 0.9215 |
| anime-char | 0.9274 | 0.1439 | 0.9209 | 0.9456 | 0.9828 | 0.9164 |
| **anime-va** | **0.9441** | **0.1244** | **0.9382** | **0.9545** | **0.9851** | **0.9382** |

**The one trained by character does worse than the one trained by voice actor.** One explanation: in this show, one voice actor rarely voices several characters, so character identity is almost the same as voice actor identity. The "push apart" objective of the by-character model also pushes apart the same character's voice in different emotions.

`anime-va` fails in the expected way: a voice actor who voices several characters gets merged together. Among the 53 wrong-merge pairs in episodes 1 and 2, Maruzensky appears twice (with `suzuka` 12 pairs, and with McQueen 9 pairs).

**Thresholds cannot be copied across.** The author warns that this model "tends to actively distinguish speakers". Measured: the median similarity of the same character is 0.337 for it, while redimnet2-b6 gets 0.541. Converted to distance, that is 0.663 against 0.460. The 0.20 to 0.90 sweep range used before is almost meaningless for it. So `compare` gained `--low` and `--high`, and each model now has its own default threshold.

Reports: `runs/score-models.json`, `runs/comparison-anime.json`.

## Dialogue coverage

`coverage` works backward from "clip boundaries should equal subtitle line boundaries" to infer the offset (episode 1: −0.95 seconds, episode 2: −0.96 seconds; all clips of both episodes fall inside subtitle lines). Then it finds dialogue lines with no clip at all.

| | Dialogue lines | With a clip | Without a clip | Line itself under 1 second | Line long enough but not cut |
| --- | ---: | ---: | ---: | ---: | ---: |
| Episode 1 (old cutting) | 409 | 243 | 166 | 53 | 113 |
| Episode 2 (old cutting) | 401 | 243 | 158 | 78 | 80 |
| Episode 3 (cut along subtitle lines) | 375 | **375** | 0 | 0 | 0 |

The old cutting method overlapped voice-detection results with the subtitles, then cut. Loudness does not tell good from bad. The 80 lines in episode 2 that were long enough but not cut have a median loudness of −25.2 dBFS on the vocal track. The 243 real clips are at −25.4, almost the same, and the quietest few of them are actually real dialogue.

What was lost was not a few stray lines but whole scenes. Gaps where a whole stretch has no clip at all, yet there is dialogue: 7 in each of the first two episodes (episode 1 has 3.7 minutes in total, including 132 seconds of dialogue; episode 2 has 6.1 minutes, including 47 seconds of dialogue).

**The labeler listened to the 7 gaps in episode 1.** The judgments are recorded in [annotations/coverage-ep01.json](../annotations/coverage-ep01.json). 3 are real lost character dialogue (89.9 seconds, 28 lines). 4 should not have been kept (134.8 seconds, 30 lines): a whole stretch of horse-race commentary, running and panting sounds, a crowd cheering, and one place where the main character hums over the sound of a TV, where voice separation cannot pull out the main character's voice.

This shows that **keeping every subtitle line also pulls in TV commentary and crowd cheers.**

`extend` has already added the dialogue lines with no clips to the clip tables of the first two episodes (episode 1 from 242 to 408 clips, episode 2 from 243 to 401, the shortest 0.42 seconds). None of the existing 485 clips was changed, so all the labels are still valid.

Reports: `runs/coverage/ep01/`, `ep02/`, `ep03/`.

## Score normalization

The idea: short clips are not much like anyone, so that is a global offset. First measure how similar each clip is to a pile of unrelated clips, subtract that, then compare. 98790 pairs, redimnet2-b6:

| Method | Ranking accuracy | Equal error rate | 0 to 1.5 seconds | 1.5 to 3 seconds | 3 to 6 seconds | Across episodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No normalization | 0.9296 | 0.1412 | 0.9239 | 0.9430 | 0.9402 | 0.9215 |
| Baseline from all unrelated clips | 0.9318 | 0.1414 | 0.9216 | 0.9467 | 0.9507 | 0.9222 |
| Baseline from the 100 most similar clips only | 0.9000 | 0.1790 | 0.8824 | 0.9250 | 0.9278 | 0.8842 |

Ranking accuracy rose by only 0.0022. The equal error rate went from 0.1412 to 0.1414, slightly worse, and the short clips that should benefit most fell a little. Using only the 100 most similar clips as the baseline is worse across the board. The reason is clear: there is no separate batch of clips unrelated to this show, so the "100 most similar" include clips of the same character. That amounts to using same-character scores as the baseline.

On WeSpeaker this method did help (0.8774 → 0.8922, error rate 0.1932 → 0.1778). But after normalization it is still below redimnet2-b6 without normalization, at 0.9296, so it does not change the model choice.

**Only the separability was measured, not the grouping.** The merge rule only decides which distances count as linked. It cannot change the distances themselves. If the clips cannot be separated, there is no point going further.

## Padding with neighboring audio

The idea: the model hears too little sound. So borrow neighboring audio from both sides to fill it up, keeping the clip's own time range. 485 fixed clips from episodes 1 and 2, redimnet2-b6:

| Minimum audio length | Ranking accuracy | Equal error rate | 1 to 1.5 seconds | 1.5 to 3 seconds | 3 to 6 seconds | Across episodes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No padding | 0.9296 | 0.1412 | 0.9239 | 0.9430 | 0.9402 | 0.9215 |
| Padded to 1.5 seconds | 0.9317 | 0.1386 | 0.9257 | 0.9430 | 0.9402 | 0.9242 |
| Padded to 2 seconds | 0.9309 | 0.1432 | 0.9231 | 0.9435 | 0.9402 | 0.9245 |
| Padded to 3 seconds | 0.9175 | 0.1668 | 0.8982 | 0.9402 | 0.9402 | 0.9112 |

When padded to 1.5 seconds, the short band rose from 0.9239 to 0.9257. The two bands above 1.5 seconds did not change at all. They did not need padding, so they serve as a control, showing that the change really came from the padding. But the gain is only 0.0018, which amounts to nothing. Padding further makes it worse. Padded to 3 seconds, the short band drops to 0.8982, because more and more of the borrowed audio is other people speaking.

**Conclusion: the weakness of short clips is neither a problem of score calibration nor a lack of context.** Re-cutting short clips along the whole subtitle line does not help either. A whole line is only about 0.1 seconds longer than the clip. The clips are short because the subtitle lines themselves are short.

## Two-step grouping

Done when all 485 clips of episodes 1 and 2 had been labeled (445 with names). The conclusion still holds. The method first grouped only the clips at least 1.5 seconds long, then attached the short clips to the nearest group. On the 62 sampled labels it looked like zero wrong merges, with 19 more linked pairs. On the full set of labels:

| Method (redimnet2-b6, threshold 0.50) | Linked | Wrong merges | Missed merges |
| --- | ---: | ---: | ---: |
| Average-linkage merge | 5745 | **68** | 4876 |
| Two-step | 6364 | **1057** | 4257 |

It links 619 more pairs, at the cost of 989 more wrong merges. 870 of those come from one spot: 87 `teo` clips and 10 Daiwa Scarlet clips were merged into one group. Without that spot, wrong merges are still 187 pairs against 68. Compared bucket by bucket at each wrong-merge limit, the two methods trade wins. The gaps are small and change back and forth with the threshold, which is not a reason to replace one with the other.

## Merge rules

Same period, same labels. Merging by nearest pair chains different characters into one big cluster, through unnamed clips. At threshold 0.40 this already gives 271 wrong-merge pairs, and at 0.50 it gives 705. The rule of "mutual nearest neighbors" links almost nothing (after 0.55 it stops changing at all). Merging by farthest pair keeps zero wrong merges up to 0.66, but it always links fewer pairs than average linkage. Of the 284 settings, the best ones with "no more wrong merges and no fewer linked pairs" were all average linkage.

## 62 sampled labels

Those labels have been deleted, so none of the numbers can be recomputed, and they should no longer be cited. What remains are the lessons:

- **"Zero wrong merges" was a small-sample illusion.** On 62 labels, the grouping in use reported zero wrong merges. On 445 labels it is 68 pairs.
- **"All the missed merges are short clips" was also an illusion.** At the time it was said that "of the 31 pairs where both sides are at least 1.5 seconds long, none was missed". On the full labels, 27.6% of such pairs still fail to link.
- **Tuning and scoring on the same labels hides problems.** The two-step method had zero wrong merges on the old labels, but 1057 pairs on the full labels. Its 1.5 second cut and its 0.05 lead margin were both chosen on that batch of labels.
- The nearest-neighbor hit rate was also overestimated: 95.9% over 49 queries, 92.0% over 438 queries, and only 81.3% when averaged by character.
- The share of different-character pairs falling inside the threshold went from "under 1%" to 3.0%.

Two more things were done in that period. Their conclusions are kept, but their evidence can no longer be recomputed. Switching to WeSpeaker had no advantage: none of 142 settings beat redimnet2-b6. A few identity references gave limited gains, and could also spread wrong people already mixed into the original groups. The related code is kept in `evaluation/references.py`.

## Limits of the evidence

- All conclusions rest on three episodes of one series. Another series would need to be checked again.
- Episodes 1 and 2 mix two cutting methods. The original 485 clips use the old overlap-based cutting, and the 324 added later are whole subtitle lines. Episode 3 is all whole subtitle lines.
- One doubt is not ruled out for episode 3. In the same 1.5 to 3 second band, episode 3 scores 0.8975, while episodes 1 and 2 score 0.9430. Whole subtitle lines include the silence before and after the speech, which dilutes the voiceprint. That is a reasonable explanation, but the episodes also differ among themselves, and the two cannot be separated. The 324 clips added later to episodes 1 and 2 could settle this, because they come from the same episodes and the same length bands but use a different cut. On 2026-10-23, 230 of them were labeled in the interface. But they are labeled only as `teo` or "Other", so only Teio's pairs can be compared, and this has not been measured yet.
- "Only one person speaks in a clip" has always been an assumption. In rapid-fire dialogue, boundary errors can pull the neighbor's speech into a clip. In episode 1, 44% of detected speech segments were found to differ in speaker from the segment before, with a gap of under 0.25 seconds.
