import { defineConfig } from "@playwright/test";

/* Records the README demo: a script in a real browser against a running avoc, with the video kept. Not a test,
   so it is not part of `npm run e2e`. How to run it is in demo.spec.ts. */
export default defineConfig({
  testDir: ".",
  outputDir: "../../data/demo-out",
  workers: 1,
  timeout: 180_000,
  reporter: "list",
  use: {
    baseURL: process.env.DEMO_URL ?? "http://127.0.0.1:8780",
    /* The Chrome already on the machine: it plays the H.264 video pieces, which Playwright's own Chromium cannot. */
    channel: "chrome",
    viewport: { width: 1280, height: 800 },
    video: { mode: "on", size: { width: 1280, height: 800 } },
  },
});
