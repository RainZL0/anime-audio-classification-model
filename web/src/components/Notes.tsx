import { cn } from "cn";
import type { ReactNode } from "react";

/* Small blocks of text used in many places. */

/* A short hint under or beside something, in small gray type; `warn` makes it orange, for something to check. */
export function Note({
  warn,
  className,
  children,
}: {
  warn?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "text-[13px] leading-relaxed text-muted-foreground",
        warn && "text-warning",
        className,
      )}
    >
      {children}
    </div>
  );
}

/* What a view shows when it has nothing to list, or while it loads. */
export function Empty({
  title,
  className,
  children,
}: {
  title?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={cn("mx-auto my-15 max-w-[560px] text-center text-muted-foreground", className)}>
      {title && <h2 className="mb-2 text-xl font-semibold text-foreground">{title}</h2>}
      {children}
    </div>
  );
}

/* A first-time explanation at the top of a view. */
export function Welcome({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="my-3 rounded-xl border bg-muted/50 px-4 py-3.5 text-[13px] text-muted-foreground">
      <h3 className="mb-1 text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </div>
  );
}
