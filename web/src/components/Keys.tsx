import type { ReactNode } from "react";
import { Kbd } from "@/components/ui/kbd";

/* Text with keys written in square brackets, such as "Press [Z] to undo", drawn with each key as a key cap (see
   docs/UI_DESIGN.md: every key shown on the page is a key cap). The text stays one string inside tr(), so both
   languages are still written side by side. */
export function withKeys(text: string): ReactNode {
  const parts = text.split(/\[([^\]]+)\]/);
  if (parts.length === 1) return text;
  /* One span, so the text and keys flow as one line even inside a box that lays out its children side by side,
     such as a hover hint. */
  return <span>{parts.map((part, i) => (i % 2 ? <Kbd key={i}>{part}</Kbd> : part))}</span>;
}
