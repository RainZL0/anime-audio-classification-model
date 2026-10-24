import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { App } from "./App";
import { startLanguage } from "./language";
import "./index.css";

startLanguage();

/* App only rewrites the address with replaceState, which fires no hashchange. So this fires only when the person
   edits the address or opens a link to another spot; reloading reads the new position. */
addEventListener("hashchange", () => location.reload());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Hints show after a short pause, so they don't flicker up while the mouse just passes over. */}
    <TooltipProvider delay={500}>
      <App />
    </TooltipProvider>
  </StrictMode>,
);
