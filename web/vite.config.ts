/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/* Where `avoc app` listens by default. In development, the API and the media go to it. */
const SERVER = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  /* The server serves the built files under /static/. */
  base: "/static/",
  build: {
    outDir: "../src/avoc/app/static",
    emptyOutDir: true,
    rolldownOptions: {
      /* Fixed names, no content hash: the server makes the browser check every page file on each
         load, and fixed names keep the git history of the built files readable. */
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    proxy: { "/api": SERVER, "/media": SERVER },
  },
});
