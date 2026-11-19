---
name: release
description: Prepares a release on request: picks the semver bump, moves Unreleased changelog entries under a dated version, and names the tag for a human to push. Use when someone asks for a release.
---

# Release

Used by: `release-manager`.

## When to use

- Someone with the authority to ship has asked for a release.
- Never on your own initiative.

## Steps

1. Confirm the request, and read the changelog's `## [Unreleased]` section and the merged changes since the last tag.
2. Choose the semver bump: major for a breaking change, minor when something was added, and patch when there are only fixes.
3. Update the version file, and move the Unreleased entries under `## [X.Y.Z] - YYYY-MM-DD` with today's date. Leave `## [Unreleased]` empty.
4. Commit the change on a release branch, and run the full gate: `python .factory/gates/gate.py`.
5. Name the tag, `vX.Y.Z`, for a human to create and push. Never push a tag or publish a release yourself.

## Done when

- The version follows semver from the changelog's entries.
- The changelog has a dated section for the new version, holding every former Unreleased entry, and `## [Unreleased]` is empty.
- The gate passed, and a human has the tag name to push.
