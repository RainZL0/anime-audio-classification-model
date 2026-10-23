import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startLanguage } from "./language";
import "./style.css";

startLanguage();

/* App only rewrites the address with replaceState, which fires no hashchange. So this fires only when the person
   edits the address or opens a link to another spot; reloading reads the new position. */
addEventListener("hashchange", () => location.reload());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
