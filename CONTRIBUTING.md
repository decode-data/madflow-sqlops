# Contributing to madflow-sqlops

All changes land via pull request against `main` — direct pushes are disabled by branch protection.

## Scope discipline

This package is deliberately narrow (see README → Non-goals). A PR that adds lineage tracking, rule evaluation, a rules/ruleset YAML, or any `decode-madflow`-specific type to the public API will be asked to justify why it belongs here rather than in a consuming project. When in doubt, open an issue before the PR.

## GDTO version changes

This package pins a specific GDTO schema version (see README). If a PR bumps that pin:

- Check the target version actually exists and is released in [decode-data/gdto](https://github.com/decode-data/gdto).
- Update the bundled schema file/constant and re-run the golden-file tests against the new schema.
- Note the version bump explicitly in the PR description.

## Testing

Once the fixture/golden-file suite exists (see README → Testing), CI will require it to pass before merge. A PR changing tagging behavior needs a fixture demonstrating the change.

## Review

Sole maintainer currently — required approving reviews is set to 0 so merges aren't blocked, but every change still goes through a PR. This will change once there are other regular contributors.
