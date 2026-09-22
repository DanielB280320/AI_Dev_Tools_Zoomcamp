import { defineConfig, devices } from "@playwright/test";

/**
 * The suite drives the real app: the two containers `docker-compose.yaml`
 * defines, with the frontend served by the API, so a single origin answers
 * both the pages and `/auth`, `/sessions`, `/events`.
 *
 * Run plainly, it starts that stack itself and waits for `/health`; an already
 * running one is reused, which is what you want while writing tests, and on CI
 * it is always started fresh.
 *
 * `E2E_BASE_URL` instead points the suite at a stack someone else is managing,
 * and then nothing here touches Docker. That is how the containerised runner
 * works (`docker-compose.e2e.yaml`, where the app is `http://app:8000` and
 * there is no Docker CLI to call), and it is also how you would aim the suite
 * at a deployed environment.
 */
const externalStack = !!process.env.E2E_BASE_URL;
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8000";

/**
 * The clipboard API exists only in a secure context. Plain http counts as one
 * on localhost but not on any other host, so reading back what "Copy join
 * link" copied would fail against, say, `http://loopboard:8000` — the origin
 * the containerised runner uses. This tells Chrome to treat that origin as
 * secure, which is exactly the browser-level exemption localhost already gets.
 */
const origin = new URL(baseURL).origin;
const trustedByDefault = ["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseURL).hostname);
const launchOptions = trustedByDefault
  ? {}
  : { args: [`--unsafely-treat-insecure-origin-as-secure=${origin}`] };

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  // The realtime assertions wait on a Server-Sent Event making the round trip
  // through the API, so they are slower than a click-and-assert test.
  timeout: 90_000,
  expect: { timeout: 20_000 },

  use: {
    baseURL,
    // "Copy join link" writes to the clipboard, and the test reads it back.
    permissions: ["clipboard-read", "clipboard-write"],
    launchOptions,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: externalStack
    ? undefined
    : {
        command: "docker compose up --build",
        cwd: "..",
        url: `${baseURL}/health`,
        reuseExistingServer: !process.env.CI,
        // A cold `docker compose up --build` builds the frontend and the image.
        timeout: 600_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
