"""EduVulcan notification conversion: fixed school rules and output proposals.

The rule, text, and child modules are pure domain logic plus family-scoped
reads; they never write database rows. ``conversion`` owns the persisted
lifecycle: claiming, atomic output persistence, retries, and pruning.
"""
