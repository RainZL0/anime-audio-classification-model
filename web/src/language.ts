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
