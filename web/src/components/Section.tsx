import type { ReactNode } from "react";
import { Field, FieldLabel } from "@/components/ui/field";

/* One part of a form, such as "Format" on the Export page: a short dark title, with a few gray words after it
   when needed ("optional", "ASS or SRT"), then the box or buttons, then any longer explanation in a Note below.
   The title is clearly bigger and darker than the notes, so the parts of the form are easy to tell apart. */
export function Section({
  title,
  aside,
  children,
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Field className="gap-2">
      <FieldLabel className="text-sm font-semibold">
        {title}
        {aside && <span className="font-normal text-muted-foreground">{aside}</span>}
      </FieldLabel>
      {children}
    </Field>
  );
}
