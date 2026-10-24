import { defineConfig } from "@playwright/test";

/* Browser tests: the built page, served by avoc over a small made-up workspace (e2e/server.py). Build first
   (npm run build), since avoc serves the built files. */
const PORT = 8799;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  /* One server and one workspace, changed by the tests, so they run one after another. */
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    /* The Chrome already on the machine, so no browser download is needed. */
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `uv run python web/e2e/server.py ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/state`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
