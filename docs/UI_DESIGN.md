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
- **A hover hint says only what the screen does not already say.** It is for: what a short label means or why it is there ("Low quality", "No text to export"); what a button does when its words or icon alone do not say it (a button with only an icon, "Reference", "Cut again"); an action that cannot be seen (Shift+click, double-click); and the full text of something cut short, such as a long file name. There is no hint that repeats the label in other words ("Undo" → "Undo the last step"), shows the name already written next to an avatar, or says "Press 1" next to a key cap that already shows it.
- **Everything that can be clicked reacts under the mouse**, so a person can tell it does something before clicking.
- **A choice that labels the line shows it most clearly on hover**: under the mouse, a "who is it" chip or a guess on the left gets a solid border in the main color and a light shadow. The machine's top guess keeps its accent background (see [Color](#color)), so the hover look tells which one a click will pick.
- **Selecting and playing are kept apart.** In a list with tick boxes, the box selects and the rest of the row plays the line.

## Color

The colors below are the theme's color names (set in `web/src/index.css`), not fixed colors; see [DECISIONS.md](DECISIONS.md#settled).

- **A filled button in the main color** (`primary`) is the step the app suggests next: accept the machine's top guess (Enter), confirm the rest (Shift+Enter), save in a dialog, start an export. No button is filled only to stand out.
- **The accent background with a stronger border** marks the machine's top guess among the choices (on the left, and under a group), the item that is selected now, and the button that is on in a row of joined buttons.
- Green means confirmed, orange means waiting to be checked, red means low quality. A dashed outline means a hint that may be wrong ("Maybe someone new", "Maybe missed").

## Typing

- **No text box unless typing is the only way.** People pick characters by avatar, chip or key, not by typing names; there is no search box for characters.
- The one place to type a character's name is the "New character" dialog, and there it can be left blank. Renaming and merging are in the Characters view.
- **Every box for a file or folder path has a "Browse…" button right after it.** It opens the system's own file window, in the folder of the path already in the box, or else in the folder `avoc app` was started from. Pasting a path into the box still works. Files cannot be dragged in ([why](DECISIONS.md#settled)).

## Layout

- The top bar stays on one line and inside the window. As the window narrows, the least needed parts are left out whole rather than cut short: first the training note (it still shows while retraining), then the progress text (the bar stays), then the "All episodes" label. The buttons do not move off screen.
- **Each part fits the width of its own area, not of the window**, because the divider between the stage and the list can make either side narrow. When there is not enough room, parts wrap or move to a line of their own: text is never squeezed into a thin column, a name never shrinks to nothing, and nothing scrolls sideways.
- **A box is as wide as what it holds needs**, so there is no wide empty gap, for example between a name and its numbers.
- **The summary at the top of a list stays on screen while scrolling**, as in Scenes, where the episode, its counts and the filters stay above the stuck scene header. shows which episode each line is from.**
- Choices of the same kind sit together in one row.
- A button that cannot be used yet is shown grayed out, not hidden, so nothing jumps when it becomes usable. For example, the chips under a group stay gray until a line is ticked.
- A count is shown once, next to what it counts, not repeated on every button.
