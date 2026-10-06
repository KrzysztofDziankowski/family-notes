import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// Local secrets (E2E_USERNAME, E2E_PASSWORD, app env) come from the gitignored
// env file. In CI the file is absent and the variables come from the job.
if (existsSync('.env')) process.loadEnvFile('.env');

// 20121 was detected from README.md (`runserver '[::]:20121'`) and the
// DJANGO_CSRF_TRUSTED_ORIGINS in .env.example. E2E_PORT overrides it when that
// port is taken on this machine.
const PORT = Number(process.env.E2E_PORT ?? 20121);
const baseURL = `http://localhost:${PORT}`;

// The E2E server runs on its own SQLite file, so tests never touch the dev
// database from .env. Django's load_dotenv does not override variables that
// are already set, so DB_NAME below wins over the one in .env.
const E2E_DB = resolve('playwright/.data/e2e.sqlite3');
mkdirSync(resolve('playwright/.data'), { recursive: true });

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: 'playwright/.auth/user.json' },
      dependencies: ['setup'],
    },
  ],
  webServer: {
    // No build step in Django: migrate + seed the test family (test_rodzic and
    // friends, scripts/dev/seed_test_family.py), then the dev server on the port
    // above. Production gunicorn needs DEBUG=False, which forces HTTPS and
    // Google OAuth, so it cannot serve a local run.
    command:
      'uv run python manage.py migrate --noinput' +
      ' && uv run python manage.py shell < scripts/dev/seed_test_family.py' +
      ` && uv run python manage.py runserver 127.0.0.1:${PORT} --noreload`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: { DB_ENGINE: 'sqlite', DB_NAME: E2E_DB, DJANGO_DEBUG: 'True' },
  },
});
