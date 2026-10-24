# Interface design rules

The rules the labeling web app keeps, so a person learns each thing once. To change how something looks or works, change the rule here first, then the code. How to use each view is in [USAGE.md](USAGE.md#labeling-and-correction-interface).

Two words used below:

- A **chip** is a rounded button with a small picture and a name, like the ones in the bottom bar.
- A **pill** is a small rounded label inside a line of text, like "Confirmed" or "Check 52%".

## What the interface is for

- Avatars are the main way to identify people, and names can be left blank. Until an avatar is cropped, a default picture that is easy to tell apart from the others is shown. Users crop the avatars from the picture themselves.
- Keyboard first. Most of the time, pressing Enter accepts the prediction. Every step can be undone.
- The day color scheme is the default.
- Clips that are hard to call do not get a separate view. Filter them out in Scenes with "Only to do". The Characters view starts with the least confident clips, so the wrong ones can be picked out, and the rest are confirmed with one key.
- When a clip is not similar to any known character, show "may be someone not seen before", and do not force a name onto it.
- **Label only the characters you want.** A user may want one character or several, and may change their mind halfway through. They should not be forced to name every line of the whole episode. Only the target characters get names. Everyone else is "Other". Target characters can be added or removed at any time, and existing labels stay valid. [HOW_IT_WORKS.md](HOW_IT_WORKS.md#labeling-and-correction-interface) explains how it works.

## The same thing looks the same everywhere

- **Same action, same look, same words, same key**, wherever it appears. If a person has learned it in one place, they already know it in the next.
- **"Who is it" choices are chips.** A target character is a chip with its avatar, "Other" a chip with a gray dot, "New character" a chip with a "+". They appear in the bottom bar and under each group in Groups, in the same order (target characters, then "Other", then "New character") and with the same keys shown on them: 1 to 9 for the first nine characters, Q for "Other", N for "New character".
- **The machine's guess of who someone is** is always the same pill: a small avatar, "Closest" and the name, and the chance when there is one. It is used in the line lists, in the "Other" list, and at the top of each group.
- **Every key shown on the page is a key cap**, never a plain letter: right after a button's words, on chips, in hover hints, dialogs and messages.
- **A state or problem has one short label, and its explanation is in the label's hover hint.** The label uses the same words everywhere it appears, for example "No text to export" on the stage and in the lists. The long text is not shown next to it, and the same problem never shows up in two wordings.
- **One thing, one name.** The label for everyone else is called "Other" (「其他」) everywhere, and no character can take that name: typing it where a name is asked for is refused. Two buttons side by side must not start with the same word unless they do the same kind of thing.
- **Picking several uses tick boxes**, as in Groups and Export. Picking one of a few uses a row of joined buttons, as in "Whole episode / Only to do". Picking several must never look like picking one.
- **Say what the person gets, not what the program does.** A title or note answers the person's question ("what is this for me, do I need it?"), for example the note under "Secondary subtitles", "only for you: it changes nothing in how lines are cut or who the machine thinks is speaking", not the program's own name for the file.
- **Every failed check says what to do next**, in steps a newcomer can follow, with links and the exact command. The steps are written once, where the check is listed (for the Hugging Face token: under "This machine"); other places that need them link there.
- **Each explanation lives in one place.** How the views fit together and how to go from the first label to the export is in the getting-started guide only, not again at the top of a view. An empty workspace shows the same "Add an episode" form as the dialog, not a page of its own; there it also lists every machine check with a tick, while the dialog shows only problems.
- **A hover hint says only what the screen does not already say.** It is for: what a short label means or why it is there ("Low quality", "No text to export"); what a button does when its words or icon alone do not say it (a button with only an icon, "Reference", "Cut again"); an action that cannot be seen and is not common knowledge (double-click; Shift+click to tick a run of boxes is common knowledge, so it gets no hint); and the full text of something cut short, such as a long file name. There is no hint that repeats the label in other words ("Undo" → "Undo the last step"), shows the name already written next to an avatar, or says "Press 1" next to a key cap that already shows it.
- **Everything that can be clicked reacts under the mouse**, so a person can tell it does something before clicking. A row in a list that selects a line or a character gets a light background on hover and keeps the normal arrow; the hand is kept for buttons, chips and tick boxes, which act on something.
- **A choice that labels the line shows it most clearly on hover**: under the mouse, a "who is it" chip or a guess on the left gets a solid border in the main color and a light shadow. The machine's top guess keeps its accent background (see [Color](#color)), so the hover look tells which one a click will pick.
- **The selected line looks the same in every list**: a border in a light main color, the accent background and a light shadow. Only the line is marked, not the box around it, such as a group's card.
- **Selecting and playing are kept apart.** In a list with tick boxes, the box selects and the rest of the row plays the line. The box takes the whole left end of the row, top to bottom, so it is easy to hit; only that part shows the hand and has its own hover color, so it is clear where it ends.

## Color

The colors below are the theme's color names (set in `web/src/index.css`), not fixed colors; see [DECISIONS.md](DECISIONS.md#settled).

- **A filled button in the main color** (`primary`) is the step the app suggests next: accept the machine's top guess (Enter), confirm the rest (Shift+Enter), save in a dialog, start an export. No button is filled only to stand out.
- **The accent background with a stronger border** marks the machine's top guess among the choices (on the left, and under a group), the item that is selected now, and the button that is on in a row of joined buttons.
- Green means confirmed, orange means waiting to be checked, red means low quality. A dashed outline means a hint that may be wrong ("Maybe someone new", "Maybe missed").

## Typing

- **No text box unless typing is the only way.** People pick characters by avatar, chip or key, not by typing names; there is no search box for characters.
- A character's name is typed in only two places, both the app's own dialogs, never the browser's: "New character", where it can be left blank, and "Name" / "Rename or merge" in the Characters view, which says before saving when the name typed merges two characters.- **Every box for a file or folder path has a "Browse…" button right after it.** It opens the system's own file window in the nearest folder of the path already in the box that exists (so an export folder not made yet opens in the workspace), or else in the folder `avoc app` was started from. A default path is written in full, so the person sees where it goes. Pasting a path into the box still works. Files cannot be dragged in ([why](DECISIONS.md#settled)).

## Layout

- The top bar stays on one line and inside the window. As the window narrows, the least needed parts are left out whole rather than cut short: first the training note (it still shows while retraining), then the "All episodes" label. What belongs to one episode, such as its progress, is not in the top bar but in the summary at the top of Groups and Scenes. The buttons do not move off screen.
- **Each part fits the width of its own area, not of the window**, because the divider between the stage and the list can make either side narrow. When there is not enough room, parts wrap or move to a line of their own: text is never squeezed into a thin column, a name never shrinks to nothing, and nothing scrolls sideways.
- **A box is as wide as what it holds needs**, so there is no wide empty gap, for example between a name and its numbers.
- **The summary at the top of a list stays on screen while scrolling**, as in Groups and Scenes, where the episode, its progress, its counts and the filters stay at the top; in Scenes the stuck scene header sits right below them.
- **A list that covers all episodes shows which episode each line is from.**
- **A form is split into parts, each with a title**, as in Export and Add an episode. The title is short, dark and bold, with at most a few gray words after it ("optional", "ASS / SRT"). Under it come the box or buttons, then any explanation in gray, one size smaller. Longer reasons go in that gray text, never in brackets in the title. The space between parts is clearly bigger than the space inside one.
- Choices of the same kind sit together in one row.
- **The top bar holds only where to go and settings**: the episode, the views, language, colors, the guide and the shortcuts. Actions on lines live where the lines are labeled; "Undo" sits at the right end of the bottom bar, next to the choices it takes back.
- **The page starts in the browser's language**, which may not be the person's. Until they pick one, the first page has a light line at the top, "界面语言 / Language: 中文 · English", written in both languages so it can be read whichever one is showing. Picking either, there or with the language button, keeps the choice and the line goes away. It is the only text on the page written in both languages.
- A button that cannot be used yet is shown grayed out, not hidden, so nothing jumps when it becomes usable. For example, the chips under a group stay gray until a line is ticked, and the chips in the bottom bar stay gray until a line is selected or ticked.
- A count is shown once, next to what it counts, not repeated on every button. The orange number of lines still to do is the one exception: it is on the Scenes tab for this episode and beside each episode in the episode menu, so a person can see which episodes need work. The Characters tab has its own: the lines the machine gave the target characters that no one has checked, in all episodes. Groups has none, because its lines are the ones counted on Scenes, and Export has nothing to do.
- A chance is never written as 100%: the machine is never certain, so 99.6% shows as 99%. Next to "Maybe someone new" no chance is shown, because it is a chance among the known characters only.
- Wherever percentages are listed, the page says once, in plain words, that they are the machine's probability; every percentage pill also says so in its hint. A line in "Maybe missed" shows only the chance of the character it may belong to: the chance of its current owner would mostly be the rest of 100%.
- Short messages show at the bottom, above the bottom bar; **while a dialog is open they show at the top of the window**, so they never cover its buttons.
