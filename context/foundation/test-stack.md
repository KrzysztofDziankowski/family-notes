# Test stack

## E2E

<!-- Written by /10x-e2e-setup. Re-run it to change this section; other skills only read it. -->

- runner: Playwright Test, @playwright/test 1.63.0
- config: playwright.config.ts
- single-spec command: npx playwright test tests/e2e/<name>.spec.ts
- full-suite command: npx playwright test
- base URL: http://localhost:20121
- port: 20121 (detected from README.md `runserver '[::]:20121'` and .env.example CSRF origins; detected default 20121, override with E2E_PORT)
- web server command: uv run python manage.py migrate --noinput && uv run python manage.py shell < scripts/dev/seed_test_family.py && uv run python manage.py runserver 127.0.0.1:$E2E_PORT --noreload (Django dev server, DJANGO_DEBUG=True, on its own SQLite DB playwright/.data/e2e.sqlite3; no build step); reuseExistingServer outside CI
- auth setup project: setup (tests/e2e/auth.setup.ts), credentials from E2E_USERNAME / E2E_PASSWORD in .env (local seed user test_rodzic, parent)
- storageState: playwright/.auth/user.json (gitignored)
- seed: tests/e2e/seed.spec.ts — protects auth-gate-roundtrip: a signed-out visitor opening a protected page is sent to sign-in and returned to that page after signing in
- browser CLI: playwright-cli (Chromium via .playwright/cli.config.json; use -s=10xdev), command skill at .claude/skills/playwright-cli/SKILL.md
- updated: 2026-10-06
