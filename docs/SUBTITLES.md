# Subtitle text: what is cleaned, and what to do when it warns

This page is for people and for AI agents helping them. It covers how the words people say are taken out of subtitle text, the warning shown when a file has marks the program does not know, and the two ways to handle such a file. How files are read whatever their encoding, and how dialogue styles are picked, is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md#flow).

## What is cleaned automatically

Subtitles made for viewers who cannot hear add things nobody says. Before subtitle text is used for export, each line goes through the rules in `src/avoc/stages/captions.py`. That file is the only place that knows these habits:

| Habit | Example | Result |
| --- | --- | --- |
| Speaker name in brackets, also when wrapped onto the next line or alone on the line above | （テイオー）ねえ | speaker テイオー, words ねえ |
| Speaker name before a colon (in Latin letters only if in capitals) | リオナタール：何か, JOHN: Wait! | speaker リオナタール, words 何か |
| Sound note or sign in brackets | （歓声）, [laughs], [ﾏｲｸ], 【回想】 | removed |
| Song lyric: a line that starts with a music note | ♪ 光の速さで | line left out |
| Marks around words that are spoken | 《 》, ＜ ＞, (( )) | marks removed, words kept |
| Arrows, emoji and other signs | ➡, 🎤, 📱, a leading `mic` | removed |
| How a kanji word is read, in brackets after it | 中山(なかやま) | reading removed |
| Half-width katakana | ﾏｲｸ | made full width |
| A dash opening each speaker's line | - Hey. | dash removed |

Speaker names are kept apart from the words. Export uses them to leave out clips that have someone else's line mixed in ([how](HOW_IT_WORKS.md#labeling-and-correction-interface)). Every case comes from real subtitles, and each has a test in `tests/test_captions.py`.

Known limit: a reading in brackets after something that is not kanji is removed too, so 「Ｇ１(ワン)」 becomes 「Ｇ１」 although the voice says 「ワン」.

## When it warns

After cleaning, lines that still contain a bracket other than the quotes 「」『』, or that start with a name and a colon, are counted. If there are any, a warning with the count and a few examples is shown by `avoc add`, `avoc styles`, `avoc set-text-subtitles`, the add form in the app, and the Export view next to the attached file. Exported text would include those marks. There are two ways to fix it.

## Way 1: convert the file to the plain subtitle format

Anyone can do this: a script, a subtitle editor, or an AI agent. The plain format is:

- SRT, saved as UTF-8.
- The times are unchanged.
- Each line of an entry is what one person says.
- When the speaker is known, the name comes first on the line in full-width brackets: （テイオー）ねえ. Brackets are used for nothing else.
- Nothing that is not spoken: no sound notes, music notes, arrows, signs or readings.

The rules leave a file in this format as it is. Use the converted file in place of the original, as the dialogue subtitles or as the text subtitles. A brief that can be handed to an agent:

> Convert `<file>` to the plain subtitle format in docs/SUBTITLES.md of the avoc project. Keep every time unchanged and keep every spoken word. Then run `uv run avoc styles "<new file>"` and check that it prints no warning about marks.

## Way 2: add a rule

When the habit will come up again, for example in every file of one subtitle group or TV station, teach it to the program. Add an entry to `CLEANUP` in `src/avoc/stages/captions.py`, or widen one of the patterns above it, and add the example line to `tests/test_captions.py`. Nothing else in the code needs to change. Then run the checks listed in the project's `CLAUDE.md`. A habit that other people will meet too is worth sending back to the project.
