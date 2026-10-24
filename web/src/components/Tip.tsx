import type { ReactElement, ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/* A hint shown on hover or keyboard focus, in place of the browser's slow, plain `title`. The child is the
   element hovered; it is rendered as is, with the hint attached. Without text, the child is shown alone. */
export function Tip({ text, children }: { text?: ReactNode; children: ReactElement }) {
  if (!text) return children;
  return (
    <Tooltip>
      <TooltipTrigger render={children} />
      <TooltipContent className="max-w-sm">{text}</TooltipContent>
    </Tooltip>
  );
}
