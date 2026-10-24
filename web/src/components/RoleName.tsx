import { cn } from "cn";
import type { Role } from "../api";
import { tr } from "../language";
import { Tip } from "./Tip";

/* A character's name. Characters not named yet are shown lighter, as a reminder that the name is temporary. */
export function RoleName({
  role,
  name,
  className,
}: {
  role?: Role;
  name: string;
  className?: string;
}) {
  const unnamed = role?.named === false;
  return (
    <Tip
      text={
        unnamed &&
        tr(
          "还没起名字，在「角色」视图里可以起",
          "Not named yet. You can name it in the Characters view",
        )
      }
    >
      <span className={cn(unnamed && "font-medium text-muted-foreground", className)}>{name}</span>
    </Tip>
  );
}
