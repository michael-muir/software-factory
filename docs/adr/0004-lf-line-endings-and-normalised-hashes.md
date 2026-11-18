# 0004 · LF line endings and line-ending-neutral hashes

Status: Accepted · Date: 2026-11-17 · Epic: E01

## Context

AC-20 requires files written UTF-8 with LF endings. This repo's own first commit already warned "LF will be replaced by CRLF", because Windows Git defaults to `core.autocrlf=true`. A target repo checked out with CRLF would show every kit file as edited if hashes covered raw bytes. Upgrades would then never update anything, and a `.factory-new` file would appear for every kit file.

## Decision

- The installer writes bytes with LF endings, using no platform newline translation.
- A hash is the SHA-256 of the file's content after normalising CRLF to LF. A checkout that only changed line endings therefore still counts as untouched.
- This repo gets a root `.gitattributes` with `* text=auto eol=lf`.
- The kit ships `.factory/.gitattributes` and `.agentic/.gitattributes` with `* text eol=lf`. A `.gitattributes` file applies to its own folder and everything below it, so target repos keep LF there without the installer writing anything at their root.

## Consequences

- Upgrades behave the same on Windows, macOS and Linux.
- An edit that only changes line endings is not treated as a local modification. That is the behaviour we want.
- Binary kit files are out of scope for v0. If one is ever added, it needs a `binary` attribute and is hashed as raw bytes.
