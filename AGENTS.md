# AGENTS.md

## Context

Read `CONTEXT.md` before making product or architecture changes. This repo is the fresh AlphaDB target-platform workspace, separate from the current Kalshi MVP repo.

## Working rules

- Preserve the target-platform/MVP boundary: this repo may define the future platform, but it must not assume control of the current live MVP.
- Prefer small, independently testable modules.
- Keep secrets and generated data out of Git.
- Use normal engineering branch prefixes such as `feat/`, `fix/`, `chore/`, and `docs/`.
