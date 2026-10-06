import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS;

test("config guide teaches the file and searches the reference", async ({ page }) => {
  await mockApi(page);
  await page.goto("/o/acme/config-guide");
  await expect(page.getByRole("heading", { name: "Configuration guide" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Config Guide" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "How settings combine" })).toBeVisible();
  await page.getByRole("textbox", { name: "Search settings" }).fill("poem");
  await expect(page.getByRole("region", { name: "reviews" })).toBeVisible();
  await expect(page.getByText("1 of")).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("textbox", { name: "Search settings" }).fill("");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/mobile.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
