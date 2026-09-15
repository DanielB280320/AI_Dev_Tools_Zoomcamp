// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// `LOOPBOARD_SPA=1 npm run build` emits a static client (dist/client, with the
// app shell prerendered to _shell.html) for the backend to serve, instead of
// the default SSR/Cloudflare bundle. The Dockerfile builds this way.
const spa = process.env.LOOPBOARD_SPA === "1";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
    ...(spa ? { spa: { enabled: true } } : {}),
  },
  ...(spa ? { nitro: false } : {}),
});
