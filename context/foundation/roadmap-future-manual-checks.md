# Future Roadmap (M-2): Remaining Manual Checks

> Status on 2026-10-05, branch `feature/m2-improved-family-capture`.
> 87 manual checks were planned. The agent ran 66 (code/wording reviews, migration on a DB copy, live OpenAI
> opt-in tests, headless Chromium at 360/1280 px) and ticked them in each plan's `## Progress`. Evidence:
> `context/changes/<id>/manual-verification.md` and `screenshots/`. The 21 below need you, a real device, or a decision.
> When you finish a group, tick the row in the matching plan's `## Progress`.

## 1. Decisions (answer, then tick or adjust)

- **S-17 1.5** — An empty capture submit is stopped by the browser's own "required" bubble, so the Polish error never
  appears (a whitespace-only submit does show it). Accept the native bubble, or add `novalidate` to the capture form?
- **S-17 2.4** — On the capture page the textarea has `autofocus`, so the first Tab goes to "Rozpoznaj", not the
  skip link. Accept (autofocus is intentional), or drop autofocus there?
- **S-02 1.3** — Skim the diminutive dictionary in `entries/classification/names.py`; confirm it covers your family's
  names.

## 2. Phone (Chrome on Android) — needs HTTPS (production) or USB port-forwarding to localhost

- **S-01 3.5** — Capture a test without a subject → answer the subject question → review shows it → save → detail shows it.
- **S-02 3.7** — In a family with "Hanna", capture about "Hania" → Hanna preselected → saved for Hanna.
- **S-05 1.8** — Gboard: send key shown; long-press diacritics and swipe typing never submit mid-word; send submits.
- **S-06 3.7** — Install FamilyNotes from the browser menu; it opens standalone at the role's home page with name + icon.
- **S-06 3.8** — In the installed app, Google and username/password sign-in both return logged in.
- **S-06 3.9** — Installed app: capture shows the indicator, then review; airplane mode while waiting → Back restores
  the capture page (text kept); resubmit after reconnecting works.
- **S-06 3.10** — Installed app in airplane mode shows "Brak połączenia"; "Spróbuj ponownie" works after reconnecting.
- **S-06 3.11** — Switch to another app during a classification and back → still-running indicator or result, never stuck.

## 3. Screen readers

- **S-06 3.12** — TalkBack announces the running state once and the slow state once.
- **S-17 4.3** — NVDA + Firefox pass over the covered flows (titles, headings, labels, errors, hints, notices in Polish).
- **S-17 4.4** — VoiceOver (iOS Safari) and TalkBack (Android Chrome): capture → review → confirm, child list/detail.
- **S-17 4.6** — Fill the NVDA/VoiceOver/TalkBack columns in `context/changes/accessible-family-flows/a11y-verification.md`.

## 4. Live classification quality (`gpt-5.4-nano` is nondeterministic)

Each of these passed in some live runs and failed in others. Run a few times
(`CLASSIFICATION_LIVE_EVAL=1 uv run python manage.py test entries.tests.test_classification_acceptance entries.tests.test_classification_live_wire`)
and decide whether the pass rate is acceptable or the model/prompt needs work.

- **S-01 2.4** — "Kartkówka z historii dla <dziecko> jutro" → subject "historia"; "Sprawdzian dla <dziecko> w piątek" asks for the subject.
- **S-02 2.6** — "Hania ma jutro dentystę" in a family with Hanna preselects Hanna (the seed family has no Hanna).
- **S-03 3.4** — "zmień datę na 15 października" and "to dla Tymka" change only the named field (the second one failed in 1 of 4 runs).
- **S-04 4.4** — Three-meetings instruction (PL and EN) → 3 proposals at 18:00 (EN sometimes returns one note).

## 5. Production (after deploy)

- **S-05 2.6** — Production capture page on Android: Enter/send submits end to end through review and save.
- **S-09 1.6** — A Google account never used with the app signs in → "not configured" status → admin maps it → family data visible.

## Findings to consider (not blocking the checks)

- **Title guard:** strips a leading name even when a second person follows ("Michał i Ania…" → "I Ania…");
  a dative name like "dla Kasi" is not stripped by the guard (the model sometimes keeps it); a date phrase
  without its preposition leaves a dangling "w".
- **Batch titles** can keep the command verb ("Dodaj spotkanie z X" instead of "Spotkanie z X").
- **Homework titles** sometimes drop the subject ("zadanie domowe"), against the S-20 decision to keep it.
- **Pre-existing prompt Polish:** "Jeśli polecenie (ani odpowiedź rodzica) nie podaje daty" →
  "Jeśli ani polecenie, ani odpowiedź rodzica nie podają daty" (`entries/classification/openai_backend.py`, `INSTRUCTIONS`).
- **Messages panel (S-15 side effect):** `base.html` now shows queued messages everywhere, so allauth's
  "Zalogowano jako test_kasia." appears on the child list, account page and chooser — above the `<h1>` there,
  below it on parent pages.
- **Chooser:** a single-family user opening `/account/family/select/` directly sees "Należysz do kilku rodzin" with
  one option (not reachable from the UI); axe noted a `target-size` issue on "Wróć do konta".
- **Fixed during verification:** model times arrived timezone-aware (`04cb2b4`); two-family header overflow,
  date/time picker focus, invisible membership logs (`077fa21`); runbook event name (`25b5574`).
- **Flaky tests seen once:** `test_manage_states` "no real names in html" (random CSRF token), `test_child_states_view` CHILD subtest.
