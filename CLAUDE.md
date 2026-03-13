# score2ly — Claude Development Guide

## Project Overview

**score2ly** converts musical scores from various input formats into LilyPond (`.ly`) format, with versioned output artifacts.

- CLI tool: `score2ly`
- GUI: `Score2LilyPond` (TBD: desktop or web app)
- GitHub: personal repo (Tom's)

## Architecture Principles

- Build in **small, reviewable steps** — each increment should be understandable and checkable by the user before moving on.
- Prefer simple, explicit code over clever abstractions until the design is proven.
- Keep CLI and GUI as thin wrappers over a shared core library.

## Input Formats

- PDF (OMR)
- Image files (PNG, JPG, etc. — OMR)
- MusicXML
- LilyPond (`.ly`) — pass-through / re-format

## Output Artifacts

- Full score in LilyPond format (primary)
- Potentially: MIDI, rendered PDF, etc. (TBD)
- All generated files are **versioned** (exact scheme TBD)

## OMR & AI Pipeline

- Use existing OMR tooling where available (e.g. Audiveris, oemer, etc. — TBD)
- Optionally integrate an LLM chatbot to improve OMR results
  - User supplies their own API key (e.g. Anthropic, OpenAI) to cover costs
- User can intervene manually at defined pipeline stages

## Tooling & Environment

- **Python** project
- **uv** for environment and dependency management
- **pyproject.toml** for project metadata and dependencies
- **git** for version control, hosted on GitHub

## Development Approach

Work **outside-in**: design the interface first with dummy implementations that are immediately runnable, then gradually replace dummies with real implementations — one piece at a time — until nothing is stubbed out and the first version is complete.

## Development Conventions

- One concern per module — keep files small and focused
- Tests live in `tests/`, mirroring the `src/score2ly/` layout
- Don't add docstrings or comments to code that wasn't changed
- Don't over-engineer: build exactly what's needed for the current step