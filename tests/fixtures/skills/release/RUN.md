# Fixture run: release

The Release Manager follows the skill once, after the product owner asked for a release.

1. Confirmed the request, and read Unreleased: one Added entry and one Fixed entry since 0.1.0.
2. Something was added and nothing broke, so it's a minor bump: 0.1.0 to 0.2.0.
3. Set `VERSION` to 0.2.0, and moved both entries under `## [0.2.0] - 2026-11-19`. Unreleased is empty.
4. Committed on `release-0.2.0`, and the gate passed.
5. Named the tag `v0.2.0` for the product owner to push.
