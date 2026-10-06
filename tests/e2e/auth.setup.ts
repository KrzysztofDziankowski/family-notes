import { test as setup, expect } from '@playwright/test';

const authFile = 'playwright/.auth/user.json';

setup('sign in once and save the session', async ({ page }) => {
  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_PASSWORD;
  if (!username || !password) {
    throw new Error('Set E2E_USERNAME and E2E_PASSWORD (see context/foundation/test-stack.md, ## E2E)');
  }

  // The allauth form is server-rendered (no client-side hydration), so input
  // typed right after load is kept and needs no retry.
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Nazwa użytkownika:' }).fill(username);
  await page.getByRole('textbox', { name: 'Hasło:' }).fill(password);
  await page.getByRole('button', { name: 'Zaloguj się' }).click();

  // Wait for a state only a signed-in user reaches.
  await page.waitForURL((url) => !url.pathname.startsWith('/accounts/login/'));
  await expect(page.getByRole('button', { name: 'Wyloguj' })).toBeVisible();

  await page.context().storageState({ path: authFile });
});
