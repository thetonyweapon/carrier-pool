import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("broker selection and dispatch board filter flow", async ({ page }) => {
  await page.goto("/brokers");
  await expect(page.getByRole("heading", { name: "Choose an operations desk" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Ithaca Freight Partners/ })).toBeVisible({ timeout: 15000 });

  await page.getByRole("button", { name: /Ithaca Freight Partners/ }).click();
  await expect(page).toHaveURL(/\/brokers\/broker-a\/loads/);
  await expect(page.getByRole("heading", { name: "Dispatch board" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Select broker" })).toHaveValue("broker-a");

  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/brokers/broker-a/loads")) requests.push(request.url());
  });
  await page.getByLabel("Status").selectOption("active");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/status=active/);
  await page.getByLabel("Status").selectOption("");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).not.toHaveURL(/status=/);
  expect(requests.every((url) => !/[?&](status|equipment|assignment_state)=(&|$)/.test(url))).toBe(true);
});

test("landing and dispatch board have no critical accessibility violations", async ({ page }) => {
  test.setTimeout(60000);
  await page.goto("/brokers");
  let results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["critical", "serious"].includes(violation.impact || ""))).toEqual([]);

  await page.getByRole("button", { name: /Ithaca Freight Partners/ }).click();
  await expect(page.getByRole("heading", { name: "Dispatch board" })).toBeVisible();
  results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["critical", "serious"].includes(violation.impact || ""))).toEqual([]);
});
