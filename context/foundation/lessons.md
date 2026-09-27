# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Prefix commits with the feature ID

- **Context**: commit naming during `/10x-implement`
- **Problem**: recent commits used inconsistent naming where one had `feat(identity-and-family-access-contract):` and one did not.
- **Rule**: Use `feat(feture-id):` prefix for commits in this change.
- **Applies to**: `implement`

## Write code in English, user-facing and OpenAI messages in Polish

- **Context**: messages visible to user/messages send to openAI
- **Problem**: current application users will be Polish users, so they need to see pages in own language, moreover prompts to OpenAI should also use user language
- **Rule**: source code must be in English, messages visible to user and messages send to openAI must be in Polish
- **Applies to**: implement, plan
