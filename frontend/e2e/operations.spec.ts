import AxeBuilder from "@axe-core/playwright";
import { expect, Page, test } from "@playwright/test";

async function signInAsAdmin(page: Page) {
  await page.getByLabel("Email or username").fill("admin");
  await page.getByLabel("Password").fill("admin");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("broker selection and dispatch board filter flow", async ({ page }) => {
  await page.goto("/brokers");
  await expect(page.getByRole("heading", { name: "Sign in to operations" })).toBeVisible();
  await signInAsAdmin(page);
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

test("authenticated shared pool appears separately from local analytics", async ({ page }) => {
  await page.goto("/brokers");
  await signInAsAdmin(page);
  await expect(page.getByRole("link", { name: "FF-101" })).toBeVisible();
  await page.getByRole("link", { name: "FF-101" }).click();
  await expect(page).toHaveURL(/\/brokers\/broker-a\/loads\/.+/);
  await expect(page.getByRole("heading", { name: "Shared carrier pool" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Shared rate estimate" })).toBeVisible();
  await expect(page.getByRole("button", { name: "SHARED POOL ON" })).toBeVisible();
});

test("landing and dispatch board have no critical accessibility violations", async ({ page }) => {
  test.setTimeout(60000);
  await page.goto("/brokers");
  let results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["critical", "serious"].includes(violation.impact || ""))).toEqual([]);

  await signInAsAdmin(page);
  await expect(page.getByRole("heading", { name: "Dispatch board" })).toBeVisible();
  results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["critical", "serious"].includes(violation.impact || ""))).toEqual([]);
});
