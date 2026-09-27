<!-- BEGIN @przeprogramowani/10x-cli -->

## 10xDevs AI Toolkit - Module 2, Lesson 5 (10xDevs 4.0 UI)

Treat a visual change as a **10x change with a design-system contract**, not a "make it pretty" chat:

```
/10x-new -> audit+reference research -> plan (tokens then one view) -> implement -> screenshot gate -> /10x-impl-review
```

### Task Router - Where to start

| Skill | Use it when |
| --- | --- |
| `/10x-ui` | A view that already renders and needs auditing and improving: theme, restyle, "nicer UI", tokens, visual pass — on the course app or any other stack. Not for building the view in the first place. |
| `/10x-research` | Locate this repo's value source and shared components, map which views read them, and pick a named motif — not a moodboard. Output is a list of charges (file, line, user impact). |
| `/10x-plan` / `/10x-implement` | Same chain as earlier M2 lessons; payload is UI. |
| `/10x-impl-review` | Before merge; do not skip visual findings as cosmetic. |

### Contract

- Two halves, whatever the stack: semantic tokens in one source, and importable components living in the repo. Tailwind v4 `@theme` + shadcn is how the course app realises them; read this repo's own realisation before proposing values.
- Values taken from outside go into the repo with a line naming the source. Not into the chat history.
- One view + global tokens. Not a whole-MVP rebrand. Not worktrees/`/goal`.
- Three charge categories: missing tokens, missing shared component, accidental architecture.
- Visual gate: a kitchen sink rendering every state, screenshotted; wire it into a screenshot test only if the repo already has one. Do not blind-update baselines.
- No design system in the repo? Proposing one is allowed — marked as adding a dependency, scoped to what the change needs, and always losing to a system that already exists.
- Models: route by phase, not vendor. Strongest model you have for audit, plan and review; a cheaper working tier for implementing charges in the loop; escalate only when the same charge survives two rounds. Any vision-capable model works, and no single model — Fable 5.1 included — is a requirement.

### Lesson boundaries

- Do not reteach Exa/Context7, worktrees, or screenshot testing as a testing course.
- Do not initialize a second design system on a repo that already has one — `shadcn init` on the course starter included.

<!-- END @przeprogramowani/10x-cli -->
