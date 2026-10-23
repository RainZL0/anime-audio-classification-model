/* The page comes in Chinese and English. The choice is kept on this machine; the first time, it follows the
   browser. Every string on screen is written as tr(Chinese, English) right where it is used. */

export type Language = "zh" | "en";

let lang: Language = "zh";

export const currentLanguage = (): Language => lang;

export const tr = <T>(zh: T, en: T): T => (lang === "en" ? en : zh);

/* English plural for a count: "1 line", "3 lines". */
export const many = (n: number, word: string, plural = `${word}s`) =>
  `${n} ${n === 1 ? word : plural}`;

export const lines = (n: number) => tr(`${n} 句`, many(n, "line"));

/* Show the language in the page's own lang attribute and title. */
const showLanguage = () => {
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.title = tr("avoc · 按角色整理动画台词", "avoc · sort anime lines by character");
};

/* Read the saved choice, or follow the browser the first time. Called once when the page starts. */
export function startLanguage() {
  const kept = localStorage.getItem("lang");
  lang =
    kept === "en" || kept === "zh"
      ? kept
      : navigator.language.toLowerCase().startsWith("zh")
        ? "zh"
        : "en";
  showLanguage();
}

/* Change the language and keep the choice. The caller re-renders the page. */
export function setLanguage(next: Language) {
  lang = next;
  localStorage.setItem("lang", lang);
  showLanguage();
}

/* The languages a voice can speak, as the server's codes. */
export const SPOKEN = ["ja", "zh", "en", "ko"] as const;

export const languageName = (code: string | null | undefined) =>
  ({
    ja: tr("日语", "Japanese"),
    zh: tr("中文", "Chinese"),
    en: tr("英语", "English"),
    ko: tr("韩语", "Korean"),
  })[code ?? ""] ??
  (code || tr("认不出", "unknown"));

/* "Chinese", or "Chinese and Japanese" for a bilingual file. */
export const languageNames = (codes: string[]) =>
  codes.length
    ? codes.map(languageName).join(tr("和", " and "))
    : tr("认不出语言", "language not recognized");
