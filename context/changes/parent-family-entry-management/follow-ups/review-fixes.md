# Review fixes — parent-family-entry-management

Queued from `reviews/impl-review.md` (2026-09-28).

- [ ] **F4, after S-02 and S-03 are both merged to master:** move the S-02 and S-03 import blocks at the end of `entries/views.py` (marked `# noqa: E402`) into the module header. Also have `save_confirmed_entry` use `_require_parent_membership` instead of its inline parent check. The same cleanup covers S-03 impl-review F3.
