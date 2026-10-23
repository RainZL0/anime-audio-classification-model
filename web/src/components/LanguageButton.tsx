import { currentLanguage, tr } from "../language";

/* Switch between Chinese and English. */
export function LanguageButton({ onSwitch }: { onSwitch: () => void }) {
  return (
    <button className="ghost lang" onClick={onSwitch} title={tr("Switch to English", "切换到中文")}>
      {currentLanguage() === "en" ? "中文" : "EN"}
    </button>
  );
}
