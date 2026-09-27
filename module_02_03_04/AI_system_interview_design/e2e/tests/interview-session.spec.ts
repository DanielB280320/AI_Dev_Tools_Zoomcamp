/**
 * The whole product in one pass, against the containers `docker-compose.yaml`
 * starts: an interviewer signs in, opens a session, shares the join link; a
 * candidate opens that link in a browser of its own and edits the board;
 * the interviewer's board shows it.
 *
 * The two clients are separate browser contexts, so they share nothing — not
 * cookies, not the localStorage the participant tokens live in. Everything
 * that crosses between them crossed the API.
 */
import { expect, test, type Page } from "@playwright/test";

const INTERVIEWER = {
  // The demo account the backend seeds into an empty database.
  email: process.env.E2E_INTERVIEWER_EMAIL ?? "alex@loopboard.dev",
  password: process.env.E2E_INTERVIEWER_PASSWORD ?? "loopboard-demo",
  name: "Alex",
};
const CANDIDATE_NAME = "Jordan";

/** A board URL. The id is the backend's own short opaque token, not a UUID. */
const SESSION_URL = /\/session\/[a-z0-9]+$/i;

test("a candidate's canvas edit reaches the interviewer's board", async ({ browser, page }) => {
  // Unique per run: the database is not reset between runs, and the assertion
  // must not pass on a leftover node from an earlier one.
  const marker = `gateway-${Date.now().toString(36)}`;
  const interviewer = page;

  await test.step("1. the interviewer signs in", async () => {
    // Signed out, the dashboard sends us to the sign-in page itself.
    await interviewer.goto("/");
    await expect(interviewer).toHaveURL(/\/signin$/);

    await interviewer.getByLabel("Email").fill(INTERVIEWER.email);
    await interviewer.getByLabel("Password").fill(INTERVIEWER.password);
    await interviewer.getByRole("button", { name: "Sign in", exact: true }).click();

    await expect(interviewer).toHaveURL(/\/$/);
    await expect(interviewer.getByRole("heading", { name: "New interview session" })).toBeVisible();
  });

  const title = `E2E — ${marker}`;
  await test.step("2. the interviewer creates a session", async () => {
    await interviewer.getByLabel("Session title").fill(title);
    await interviewer.getByLabel("Your name").fill(INTERVIEWER.name);
    await interviewer.getByRole("button", { name: "Start session" }).click();

    // Creating a session drops the host straight onto its board.
    await expect(interviewer).toHaveURL(SESSION_URL);
    await expect(interviewer.getByText(title)).toBeVisible();
    await expect(interviewer.getByText(`you are ${INTERVIEWER.name} (interviewer)`)).toBeVisible();
  });

  let joinUrl = "";
  await test.step("3. the interviewer shares the join link", async () => {
    await interviewer.getByRole("button", { name: "Copy join link" }).click();
    // The button copies rather than displays, so the clipboard is where the
    // link a real interviewer pastes into chat actually comes from.
    await expect(interviewer.getByRole("button", { name: "Copied" })).toBeVisible();
    joinUrl = await interviewer.evaluate(() => navigator.clipboard.readText());

    const sessionId = new URL(interviewer.url()).pathname.split("/").pop();
    expect(joinUrl).toBe(new URL(`/join/${sessionId}`, interviewer.url()).toString());
  });

  // A second client: its own context, so it carries none of the interviewer's
  // credentials — exactly what a candidate opening the link elsewhere has.
  const candidateContext = await browser.newContext();
  const candidate: Page = await candidateContext.newPage();

  await test.step("4. the candidate joins from a separate client", async () => {
    await candidate.goto(joinUrl);
    await expect(candidate.getByRole("heading", { name: title })).toBeVisible();

    await candidate.getByLabel("Your display name").fill(CANDIDATE_NAME);
    await candidate.getByRole("button", { name: "Candidate (can edit)" }).click();
    await candidate.getByRole("button", { name: "Join session" }).click();

    await expect(candidate).toHaveURL(SESSION_URL);
    await expect(candidate.getByText(`you are ${CANDIDATE_NAME} (candidate)`)).toBeVisible();
    // Both clients are on the same board: the interviewer's roster says so.
    await expect(interviewer.getByTitle(`${CANDIDATE_NAME} · candidate`)).toBeVisible();
  });

  await test.step("5. the candidate changes the canvas", async () => {
    // The gesture the board advertises: drag a component off the palette.
    await candidate
      .getByRole("button", { name: "API Gateway" })
      .dragTo(candidate.locator("svg.touch-none"), { targetPosition: { x: 360, y: 220 } });
    await expect(candidate.locator("svg text", { hasText: "API Gateway" })).toBeVisible();

    // Renaming it through the inspector puts this run's marker on the board,
    // so what the interviewer sees can only have come from here.
    await candidate.getByRole("textbox").fill(marker);
    await expect(candidate.locator("svg text", { hasText: marker })).toBeVisible();
  });

  await test.step("6. the interviewer sees the change", async () => {
    // Nothing is clicked here: the node arrives over Server-Sent Events, which
    // is the assertion. The generous timeout is the round trip, not a guess.
    await expect(interviewer.locator("svg text", { hasText: marker })).toBeVisible({
      timeout: 30_000,
    });
  });

  await candidateContext.close();
});
