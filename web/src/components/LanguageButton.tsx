import { Button } from "@/components/ui/button";
import { currentLanguage, tr } from "../language";
import { Tip } from "./Tip";

/* Switch between Chinese and English. */
export function LanguageButton({ onSwitch }: { onSwitch: () => void }) {
  return (
    <Tip text={tr("Switch to English", "切换到中文")}>
      <Button
        variant="ghost"
        size="sm"
        className="min-w-11 flex-none"
        onClick={onSwitch}
        aria-label={tr("Switch to English", "切换到中文")}
      >
        {currentLanguage() === "en" ? "中文" : "EN"}
      </Button>
    </Tip>
  );
}
