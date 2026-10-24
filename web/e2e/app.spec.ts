import { expect, test, type Page } from "@playwright/test";

/* What a person does most, checked in a real browser: the top bar fits, the views switch, a line can be labeled
   and the label undone, and the dialogs open and close. The tests share one workspace, so the ones that label
   undo what they did. */

const open = async (page: Page, lang: "en" | "zh" = "en", hash = "view=scene&ep=ep01") => {
  await page.addInitScript((lang) => {
    localStorage.setItem("lang", lang);
    localStorage.setItem("guide-seen", "1");
  }, lang);
  await page.goto(`/#${hash}`);
  await expect(page.getByText("おはようございます").first()).toBeVisible();
};

for (const lang of ["en", "zh"] as const) {
  test(`the top bar fits from 800 to 1400 pixels wide (${lang})`, async ({ page }) => {
    await open(page, lang);
    for (const width of [800, 1000, 1200, 1400]) {
      await page.setViewportSize({ width, height: 800 });
      const header = page.locator("header");
      /* Nothing runs off the right edge, and no text shown in it is cut short. */
      const overflow = await header.evaluate((h) => h.scrollWidth - h.clientWidth);
      expect(overflow, `overflow at ${width}px`).toBeLessThanOrEqual(0);
      const clipped = await header.evaluate((h) =>
        [...h.querySelectorAll<HTMLElement>("*")]
          .filter(
            (e) => e.offsetParent !== null && e.children.length === 0 && e.textContent?.trim(),
          )
          .filter((e) => e.scrollWidth > e.clientWidth + 1)
          .map((e) => e.textContent),
      );
      expect(clipped, `text cut short at ${width}px`).toEqual([]);
    }
  });
}

test("the views switch with the tabs and the shortcut keys", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Characters" }).click();
  await expect(page).toHaveURL(/view=roles/);
  await page.keyboard.press("e");
  await expect(page).toHaveURL(/view=export/);
  await page.keyboard.press("g");
  await expect(page).toHaveURL(/view=groups/);
  await page.keyboard.press("s");
  await expect(page).toHaveURL(/view=scene/);
});

test("Q labels the line Other, and Z undoes it", async ({ page }) => {
  await open(page);
  const confirmed = page.getByText("Confirmed", { exact: true });
  await expect(confirmed).toHaveCount(0);
  await page.keyboard.press("q");
  await expect(confirmed).toHaveCount(1);
  await page.keyboard.press("z");
  await expect(confirmed).toHaveCount(0);
});

test("a new character is named in the app's own dialog, not the browser's", async ({ page }) => {
  await open(page);
  page.on("dialog", (d) => {
    throw new Error(`the browser's own ${d.type()} box opened`);
  });
  await page.keyboard.press("n");
  await page.getByRole("dialog").getByRole("button", { name: /Save/ }).click();
  await page.keyboard.press("o");
  await page.getByRole("button", { name: "Name", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText('Name "Character 1"')).toBeVisible();
  await dialog.getByRole("textbox").fill("Alice");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/role=Alice/);
  await page.keyboard.press("z");
  await expect(page).toHaveURL(/role=Character(%20|\+)1/);
  await page.keyboard.press("z");
  await expect(page.getByRole("button", { name: "Name", exact: true })).toHaveCount(0);
});

test("the episode menu switches episodes", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "ep01" }).click();
  await page.getByRole("menuitemradio", { name: "ep02" }).click();
  await expect(page).toHaveURL(/ep=ep02/);
  await expect(page.getByRole("menu")).toBeHidden();
});

test("the add dialog opens from the episode menu and closes with Escape", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "ep01" }).click();
  await page.getByRole("menuitem", { name: "Add an episode…" }).click();
  await expect(page.getByText("Video file")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("Video file")).toBeHidden();
});

test("the shortcuts dialog opens with ? and closes with Escape", async ({ page }) => {
  await open(page);
  await page.keyboard.press("?");
  const title = page.getByText("Keyboard shortcuts", { exact: true });
  await expect(title).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(title).toBeHidden();
});

test("dark colors are kept after a reload", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /dark colors/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: /light colors/i }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("the language button switches the page to Chinese and back", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "切换到中文" }).click();
  await expect(page.getByRole("button", { name: "角色", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Switch to English" }).click();
  await expect(page.getByRole("button", { name: "Characters", exact: true })).toBeVisible();
});
