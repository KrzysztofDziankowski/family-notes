// risk: parent-entry-lands-grouped — an entry a parent saves for a child must show on
// the family list under its own day and that child (day → assignee grouping), once.
// Not in context/foundation/test-plan.md (it plans no e2e); chosen in a /10x-e2e standalone run.
// seed: tests/e2e/seed.spec.ts
import { test, expect, type Page } from '@playwright/test';

// The app's calendar day is Europe/Warsaw (settings.TIME_ZONE), not the runner's.
function warsawDateInDays(days: number): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// The parent calendar's day heading carries the Polish calendar date ("Jutro, 8 października"),
// plus the year when the day falls in another year than today ("Jutro, 1 stycznia 2027").
function polishCalendarDate(isoDate: string): string {
  const sameYear = isoDate.slice(0, 4) === warsawDateInDays(0).slice(0, 4);
  return new Intl.DateTimeFormat('pl-PL', {
    day: 'numeric',
    month: 'long',
    ...(sameYear ? {} : { year: 'numeric' }),
    timeZone: 'UTC',
  })
    .format(new Date(`${isoDate}T00:00:00Z`))
    .replace(/ r\.$/, '');
}

async function deleteEntriesTitled(page: Page, title: string) {
  await page.goto('/entries/');
  const rows = page.getByRole('link', { name: title, exact: true });
  for (let left = await rows.count(); left > 0; left--) {
    await rows.first().click();
    await page.getByText('Usuń wpis', { exact: true }).click();
    await page.getByRole('button', { name: 'Usuń na stałe' }).click();
    await expect(page.getByRole('status')).toHaveText('Usunięto wpis.');
  }
  await expect(rows).toHaveCount(0);
}

test.describe('parent-entry-lands-grouped', () => {
  const title = `E2E wpis ${Date.now()}`;

  test.afterEach(async ({ page }) => {
    // Asserted: a cleanup that can't remove the entry turns the run red.
    await deleteEntriesTitled(page, title);
  });

  test("parent's new entry for a child shows under that day and that child on the family list", async ({ page }) => {
    test.info().annotations.push({ type: 'test-data', description: title });

    // A parent saves an entry for Kasia, dated tomorrow.
    const tomorrow = warsawDateInDays(1);
    await page.goto('/entries/create/');
    await page.getByRole('textbox', { name: 'Tytuł' }).fill(title);
    await page.getByRole('textbox', { name: 'Data' }).fill(tomorrow);
    await page.getByRole('combobox', { name: 'Dla kogo' }).selectOption({ label: 'Kasia' });
    await page.getByRole('button', { name: 'Dodaj wpis' }).click();
    await expect(page.getByRole('status')).toHaveText('Dodano wpis.');

    // The family calendar shows it in tomorrow's box under "Kasia", and nowhere else.
    await page.goto('/entries/');
    const tomorrowBox = `Jutro, ${polishCalendarDate(tomorrow)}`;
    await expect(page.getByRole('heading', { level: 2, name: tomorrowBox, exact: true })).toBeVisible();
    const kasiaTomorrow = page.getByRole('list', { name: `${tomorrowBox}, Kasia`, exact: true });
    await expect(kasiaTomorrow.getByRole('link', { name: title, exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: title, exact: true })).toHaveCount(1);
  });
});
