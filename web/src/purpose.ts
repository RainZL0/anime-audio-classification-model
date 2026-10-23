/* What the voices are collected for. Speech synthesis (TTS: GPT-SoVITS, Style-Bert-VITS2) needs the words
   actually said, in the language spoken; voice conversion (RVC) needs only the sound. With "audio", the page leaves
   out everything about that text: "No text to export", text subtitles and their warnings. The choice is kept on
   this machine, like the page language; the caller re-renders the page after a change. */

export type Purpose = "tts" | "audio";

let purpose: Purpose = localStorage.getItem("purpose") === "audio" ? "audio" : "tts";

export const currentPurpose = (): Purpose => purpose;

/* Whether the page shows what export needs in the language spoken. */
export const needsText = () => purpose === "tts";

export function setPurpose(next: Purpose) {
  purpose = next;
  localStorage.setItem("purpose", next);
}
