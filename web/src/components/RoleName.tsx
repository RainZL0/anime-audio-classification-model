import type { Role } from "../api";
import { tr } from "../language";

/* A character's name. Characters not named yet are shown lighter, as a reminder that the name is temporary. */
export function RoleName({ role, name, cls = "" }: { role?: Role; name: string; cls?: string }) {
  return (
    <span
      className={`rn ${cls} ${role?.named === false ? "unnamed" : ""}`}
      title={
        role?.named === false
          ? tr(
              "还没起名字，在「角色」视图里可以起",
              "Not named yet. You can name it in the Characters view",
            )
          : ""
      }
    >
      {name}
    </span>
  );
}
