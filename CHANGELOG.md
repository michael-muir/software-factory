# Changelog

All notable changes to Software Factory are recorded here, in the form of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- `pipeline.py check`: whether a full-track stage has passed, decided from a checkout's committed files (E13).
- `pipeline.py new`, `run`, `approve`, `reject`, `resume`, `cancel` and `status`: a full-track job driven through its plan stages under E18's lease, with the spec and design checkpoints (E13).
