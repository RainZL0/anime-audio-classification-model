# Current status and next steps

Updated: 2026-10-24. Current plans are written only here. The route up to the first release is in [ROADMAP.md](ROADMAP.md). Settled approaches are in [DECISIONS.md](DECISIONS.md).

## Where things stand

| Area | Status |
| --- | --- |
| Source material | The audio tracks of the full 13-episode season (`data/raw/`) and the Chinese subtitles (`data/ass/uma/`) are all here. Episodes 1 to 7 have been processed. Episodes 8 to 13 have not |
| Clips and voiceprints | 2689 clips across the seven episodes. Clips shorter than 0.5 seconds have no voiceprint. Voiceprints for all seven episodes have been computed with `anime-va`, `anime-char` and `redimnet2-b6`. Episodes 5 to 7 have a clip for every dialogue line. Their subtitle offset is -0.95 seconds, the same as episode 3 |
| Video and subtitles | All seven episodes have their video and subtitles recorded. Each also has Netflix Japanese subtitles attached (offsets -0.92 to -0.94 seconds) |
| Interface | The four views, Groups, Scenes, Characters and Export, all work and are still being polished. Done so far: playback speed, listening to vocals only, More context, returning to the same spot after a refresh, background pre-cutting, and so on |
| Labels | In `runs/labels/`. The only target character is Tokai Teio (label name `teo`). See the table below |
| Export | The GPT-SoVITS format has been tested for real. Of Teio's 171 clips from episodes 1 to 3, 118 passed the filter (4.0 minutes). Fine-tuning GPT-SoVITS on them sounds closer to her. Of the 503 clips from all seven episodes, 302 pass the same rule (10.7 minutes). The new version trained on them sounds somewhat closer. See "Questions being tested" below |

Labels per episode (2026-10-23 evening, status shown in the interface):

| Episode | Clips | Manually labeled | Of which `teo` | Of which "Other" | Confident | Needs review | Short lines skipped by default |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Episode 1 | 408 | 369 | 100 | 269 | 28 | 1 | 10 |
| Episode 2 | 401 | 318 | 112 | 206 | 60 | 3 | 20 |
| Episode 3 | 375 | 317 | 63 | 254 | 55 | 0 | 3 |
| Episode 4 | 378 | 73 | 42 | 31 | 292 | 0 | 13 |
| Episode 5 | 365 | 54 | 36 | 18 | 297 | 2 | 12 |
| Episode 6 | 373 | 92 | 90 | 2 | 270 | 1 | 10 |
| Episode 7 | 389 | 71 | 60 | 11 | 294 | 2 | 22 |

- `teo` has 503 confirmed clips, 16 minutes 1 second in total. Of these, 2 minutes 50 seconds are "low quality". Every clip the machine is confident belongs to `teo` has already been listened to by a person. The remaining confident clips are all "Other", and they are not confirmed one by one.
- 85 clips are labeled "low quality" (episodes 1 to 7: 26, 12, 4, 6, 8, 11 and 18). They are not used for training and are skipped on export.
- When the subtitles show two lines at the same time, each line is cut into its own clip. The two clips nearly share the same time range, and both contain two people's voices. About 50 clips in the first four episodes overlap another clip by more than 0.3 seconds. For now a person listens and labels them "low quality". The program does not handle them separately.
- "Needs review" includes clips that are shorter than 0.5 seconds and have no voiceprint.

## Questions being tested

Classifying by name is settled and is no longer being tested ([DECISIONS.md](DECISIONS.md#settled)).

**Can a model reading the same line help identify people?** Take an unlabeled clip, use its Japanese line, and have Teio's GPT-SoVITS model read it aloud. Then compare the synthesized voice with the real clip, to see how alike they sound. The words are the same, so the remaining difference is only the voice itself. For short lines this might work better than comparing voiceprints directly. Expectations are low. The character information in the synthesized voice all comes from the labeled clips, the synthesis carries its own error (the similarity between the synthesized voice and Teio's average voiceprint is 0.52 to 0.70, while the real recordings score 0.767), and the tone also follows the reference audio. This has not started yet. The rules are in next step 2.

**Does more data make GPT-SoVITS better?** Last time, after fine-tuning on 118 clips (4.0 minutes, episodes 1 to 3), the voice sounded closer. Now another version is trained with the same settings on 302 clips (10.7 minutes, episodes 1 to 7, `out/sovits-teio/dataset3/`). Its weights are named `teio7`. The old `teio` is kept untouched. The comparison: synthesize 8 lines that are not in the training data (last time's 4 lines, plus one each for excited, down, smug and determined) using the same reference audio. Do this for the base model, the old version and the new version. Compute the similarity of each to Teio's average voiceprint, then have a person listen for tone and pronunciation. If a person cannot hear an improvement, stop labeling more for GPT-SoVITS. Voiceprint similarity has been measured: without fine-tuning 0.538, old version 0.615, new version 0.646. It is still rising, but by less. GPT-SoVITS V5 without fine-tuning, averaged over 5 reference clips, scores 0.580. The new version scores 0.593, which is a tie. V5 follows the reference audio, and the new version's results go up and down. Training more rounds changes the score by only about 0.01. The similarity of the synthesized voice is already close to that of real recordings of the same length, so this measure has reached its limit. Listening by a person is still needed.

**Can `teio7` read Chinese in Teio's voice?** The reference audio stays Japanese, and the 8 test lines are Chinese. Plain `teio7` scores 0.549. Auxiliary reference audio mixes the timbre of extra clips into the voice without changing the tone. Three emotional clips (bright, sad, playful) raise the score to 0.633. Nine calm clips reach only 0.606, and both sets together 0.631, so varied clips help more than many clips. RVC (voice conversion: it keeps the words and pitch of the input and replaces the timbre) is a second step after GPT-SoVITS. It was trained with Applio on the same 302 clips, 200 epochs. Run on top, it raises plain `teio7` to 0.676 and `teio7` with the three clips to 0.688. Microsoft's online edge-tts voices XiaoyiNeural and XiaoxiaoNeural score near 0 on their own. Raised to Teio's pitch (median about 361 Hz, so 3 and 7 semitones up), RVC brings them to 0.640 and 0.627. That is about as good as `teio7` with auxiliary clips, but below `teio7` plus RVC. A person still has to listen for artifacts. The listening page is `out/sovits-teio/samples-rvc/index.html`.

## Next steps

Each episode is labeled in the correction interface, with only two labels: `teo` and "Other".

1. **Polish the interface (current focus).** A first use from scratch and the error messages must both be smooth. After that, record the demo GIF for the README. Done: `avoc add` adds an episode with one command. `--device` is chosen automatically by default. `doctor` checks the token, the models and the disk space. An empty workspace gives the command to run. Episodes whose voiceprints are not all computed are skipped. The README, docs, code comments and command-line output are now in English, and the web app has Chinese and English versions with a switch. The first-use welcome page and adding an episode from inside the interface are done too. Subtitles in any common text encoding are read, and the dialogue styles are picked automatically. They can be checked and changed with `avoc styles` and `--styles`, and with check boxes in the interface's add form. Caption marks (speaker names, sound notes, lyrics, TV caption signs) are cleaned by one set of rules; on our Netflix, Amazon and two TV-caption sources of Japanese subtitles (72 files), no line keeps a mark the rules do not know, and unknown marks are reported ([SUBTITLES.md](SUBTITLES.md)). Not done yet: showing, while labeling, the text from the text subtitles and whether each clip will export. Not done yet: actually installing and running it on Linux. Finding trial users is on hold for now.
2. **Finish labeling episode 4, and run the read-aloud comparison along the way.** 292 clips that the machine is confident are "Other" are still waiting. The Japanese subtitles are attached. The rules are fixed before labeling:
   - Compare only the yes/no question "is this Tokai Teio?", because only Teio has a fine-tuned model. The models are the existing `teio_e8_s240.pth` and `teio-e15.ckpt` (in the GPT-SoVITS folder, trained on the 118 clips from episodes 1 to 3; episode 4 was not used). The reference audio and synthesis settings follow `out/sovits-teio/infer.py`. The newly trained `teio7` used episode 4, so it cannot be used for this test.
   - Clips: episode 4 clips labeled `teo` or "Other", that have a voiceprint, and whose whole line can be matched to the Netflix Japanese subtitles.
   - For each clip, have Teio's model read its own line, and compute three scores. The new method is the `anime-va` voiceprint similarity between the real clip and the synthesized voice. Control 1 is the similarity between the real clip and the average voiceprint of Teio's manual labels from episodes 1 to 3. Control 2 is the probability the small classifier gives to Teio.
   - Report, for each of the three scores, the ranking accuracy at separating Teio from non-Teio clips (the share of times that a random Teio clip scores higher than a random non-Teio clip). Report it for all clips, and split by length: 0.5 to 1 second, 1 to 1.5, 1.5 to 3, and over 3 seconds.
   - Verdict: the new method must beat both controls by at least 0.02 in some length band before it is considered as a second opinion for that band. If no band reaches that, drop the idea.
3. **Finish the remaining 60 clips of episodes 1 and 2.** Then check whether clips of 0.5 to 1 second are still usable on more data.
4. **After the GPT-SoVITS comparison, decide whether to handle episodes 8 onward.** Each episode takes one `avoc add`, with `--text-subs` to attach the Japanese subtitles ([command](USAGE.md#processing-a-new-episode)). Label each episode as it is processed.

## Where the files are

| Content | Location |
| --- | --- |
| Each episode's clips, audio tracks, voiceprint cache, and pictures cut by the interface | `runs/episodes/ep01/` to `ep07/` |
| The interface's labels and cast table | `runs/labels/` (format in [data files](HOW_IT_WORKS.md#data-files)). |
| Teio's GPT-SoVITS dataset and scripts | `out/sovits-teio/`. `speak.py` there is a page for typing text and hearing `teio7` read it (http://127.0.0.1:9873) |
| Teio's RVC model | `C:\_projects\py\2026\Applio\logs\teio7\` (`teio7_200e_8800s.pth` and `teio7.index`) |

`runs/` and `out/` are not committed to git.
