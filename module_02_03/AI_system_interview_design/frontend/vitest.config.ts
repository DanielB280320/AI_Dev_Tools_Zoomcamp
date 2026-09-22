// Unit tests only. Kept apart from vite.config.ts on purpose: that config pulls
// in TanStack Start, nitro and the Lovable plugins, none of which a test of a
// pure module needs, and some of which expect a dev server around them.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
