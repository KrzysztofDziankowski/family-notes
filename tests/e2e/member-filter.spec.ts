// risk: member-filter — the parent calendar's child filter must switch instantly (no page
// load), show only that child's and "Ogólne" entries, and keep the selection while the parent
// moves between windows. Only a browser runs js/member-filter.js; the server-side rule is pinned
// by the Django tests (entries/tests/test_manage_views.py, MemberFilterTests).
// Plan: context/changes/child-calendar-view/plan.md, Phase 4.
// seed: tests/e2e/seed.spec.ts
import { test, expect, type Page, type Request } from '@playwright/test';

// The app's calendar day is Europe/Warsaw (settings.TIME_ZONE), not the runner's.
function warsawDateInDays(days: number): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function createEntry(page: Page, title: string, date: string, assignee: string) {
  await page.goto('/entries/create/');
  await page.getByRole('textbox', { name: 'Tytuł' }).fill(title);
  await page.getByRole('textbox', { name: 'Data' }).fill(date);
  await page.getByRole('combobox', { name: 'Dla kogo' }).selectOption({ label: assignee });
  await page.getByRole('button', { name: 'Dodaj wpis' }).click();
  await expect(page.getByRole('status')).toHaveText('Dodano wpis.');
}

async function deleteEntriesTitled(page: Page, title: string) {
  await page.goto('/entries/');
  const rows = page.getByRole('link', { name: title, exact: true });
  for (let left = await rows.count(); left > 0; left--) {
    await rows.first().click();
    await page.getByText('Usuń wpis', { exact: true }).click();
    await page.getByRole('button', { name: 'Usuń na stałe' }).click();
    // The calendar also holds the filter's status region, so pick the message by its text.
    await expect(page.getByRole('status').filter({ hasText: 'Usunięto wpis.' })).toHaveText('Usunięto wpis.');
  }
  await expect(rows).toHaveCount(0);
}

test.describe('member-filter', () => {
  const stamp = Date.now();
  const kasiaTitle = `E2E filtr Kasia ${stamp}`;
  const tymekTitle = `E2E filtr Tymek ${stamp}`;
  const generalTitle = `E2E filtr Ogólne ${stamp}`;

  test.afterEach(async ({ page }) => {
    // Asserted: a cleanup that can't remove an entry turns the run red.
    for (const title of [kasiaTitle, tymekTitle, generalTitle]) {
      await deleteEntriesTitled(page, title);
    }
  });

  test('selecting a child filters the calendar instantly and the filter survives navigation', async ({ page }) => {
    test.info().annotations.push({ type: 'test-data', description: `${kasiaTitle}; ${tymekTitle}; ${generalTitle}` });

    // A few days into the default window, so a run crossing Warsaw midnight still finds them
    // (and cleans them up) in the window starting today.
    await createEntry(page, kasiaTitle, warsawDateInDays(2), 'Kasia');
    await createEntry(page, tymekTitle, warsawDateInDays(3), 'Tymek');
    await createEntry(page, generalTitle, warsawDateInDays(3), 'Ogólne');

    await page.goto('/entries/');
    const filter = page.getByRole('navigation', { name: 'Filtr wpisów' });
    const kasiaEntry = page.getByRole('link', { name: kasiaTitle, exact: true });
    const tymekEntry = page.getByRole('link', { name: tymekTitle, exact: true });
    const generalEntry = page.getByRole('link', { name: generalTitle, exact: true });
    await expect(filter.getByRole('link', { name: 'Wszyscy', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(kasiaEntry).toBeVisible();
    await expect(tymekEntry).toBeVisible();
    await expect(generalEntry).toBeVisible();

    // "Kasia": Tymek's entry hides, Kasia's and the "Ogólne" one stay, without a page load.
    const navigations: Request[] = [];
    page.on('request', (request) => {
      if (request.isNavigationRequest()) navigations.push(request);
    });
    await filter.getByRole('link', { name: 'Kasia', exact: true }).click();
    await expect(tymekEntry).toBeHidden();
    await expect(kasiaEntry).toBeVisible();
    await expect(generalEntry).toBeVisible();
    await expect(filter.getByRole('link', { name: 'Kasia', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(filter.getByRole('link', { name: 'Wszyscy', exact: true })).not.toHaveAttribute('aria-current', 'page');
    await expect(page.getByText('Pokazano: Kasia i Ogólne', { exact: true })).toBeVisible();
    await expect(page.getByText('Pokazano: wszystkie wpisy', { exact: true })).toBeHidden();
    await expect(page).toHaveURL(/[?&]member=\d+/);
    expect(navigations).toHaveLength(0);
    const filteredUrl = new URL(page.url());
    const member = filteredUrl.searchParams.get('member');

    // "Następne" then "Wcześniejsze" keep the filter (real page loads, so the server renders it).
    const calendarNav = page.getByRole('navigation', { name: 'Nawigacja kalendarza' });
    // The expected windows come from the links themselves, not the runner's clock.
    const nextLink = calendarNav.getByRole('link', { name: 'Następne', exact: true });
    const nextStart = new URL((await nextLink.getAttribute('href'))!, page.url()).searchParams.get('start');
    await nextLink.click();
    await page.waitForURL((url) => url.searchParams.get('start') === nextStart);
    expect(new URL(page.url()).searchParams.get('member')).toBe(member);
    await expect(filter.getByRole('link', { name: 'Kasia', exact: true })).toHaveAttribute('aria-current', 'page');

    const earlierLink = calendarNav.getByRole('link', { name: 'Wcześniejsze', exact: true });
    const earlierStart = new URL((await earlierLink.getAttribute('href'))!, page.url()).searchParams.get('start');
    await earlierLink.click();
    await page.waitForURL((url) => url.searchParams.get('start') === earlierStart);
    expect(new URL(page.url()).searchParams.get('member')).toBe(member);
    await expect(filter.getByRole('link', { name: 'Kasia', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(kasiaEntry).toBeVisible();
    await expect(generalEntry).toBeVisible();
    await expect(tymekEntry).toBeHidden();

    // "Wszyscy" shows Tymek's entry again and drops member from the address bar.
    const loadsBefore = navigations.length;
    await filter.getByRole('link', { name: 'Wszyscy', exact: true }).click();
    await expect(tymekEntry).toBeVisible();
    await expect(kasiaEntry).toBeVisible();
    await expect(generalEntry).toBeVisible();
    await expect(page.getByText('Pokazano: wszystkie wpisy', { exact: true })).toBeVisible();
    await expect(page.getByText('Pokazano: Kasia i Ogólne', { exact: true })).toBeHidden();
    await expect(page).not.toHaveURL(/member=/);
    expect(navigations).toHaveLength(loadsBefore);
  });
});
