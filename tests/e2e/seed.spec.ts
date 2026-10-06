// Seed for risk auth-gate-roundtrip: a signed-out visitor who opens a protected
// page must be sent to sign-in, and after signing in must land back on that page.
// Not in context/foundation/test-plan.md (it plans no e2e); chosen during /10x-e2e-setup.
import { test, expect } from '@playwright/test';

// The risk is the signed-out path, so this test opts out of the saved session.
test.use({ storageState: { cookies: [], origins: [] } });

test('signed-out visitor is gated to sign-in and returned to the protected page', async ({ page }) => {
  const username = process.env.E2E_USERNAME!;
  const password = process.env.E2E_PASSWORD!;

  await page.goto('/entries/');

  // Gate: the family's entries are not served; sign-in remembers where to return.
  await expect(page).toHaveURL('/accounts/login/?next=/entries/');
  await expect(page.getByRole('heading', { name: 'Zaloguj się', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Wpisy rodziny' })).toBeHidden();

  await page.getByRole('textbox', { name: 'Nazwa użytkownika:' }).fill(username);
  await page.getByRole('textbox', { name: 'Hasło:' }).fill(password);
  await page.getByRole('button', { name: 'Zaloguj się' }).click();

  // Return trip: back on the page the visitor asked for, signed in.
  await page.waitForURL('/entries/');
  await expect(page.getByRole('heading', { name: 'Wpisy rodziny', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Wyloguj' })).toBeVisible();

  // No cleanup: the test creates no data, and its session lives only in this
  // test's own browser context (signing out could revoke the shared session).
});
