# score2ly — Claude Development Guide

## Project Overview

**score2ly** converts PDF musical scores into LilyPond (`.ly`) format using an OMR pipeline.

- CLI tool: `score2ly` with two subcommands: `new` (start a conversion) and `update` (resume after manual edits)
- GUI: planned for Phase 2, not started
- GitHub: personal repo (Tom's — `tomasssalles/score2ly`)
- Input: **PDF only** (no plans to expand)

## Current State (Phase 1 complete)

The full pipeline is implemented and working:

1. `01.original/` — Copy/extract of the input PDF
2. `02.pages/` — Rasterized page PNGs (with optional preprocessing)
3. `03.audiveris_omr/` — Audiveris `.omr` projects (full-score book + per-page)
4. `04.musicxml/` — MusicXML export (from Audiveris, or user-provided via `--xml`)
5. `05.musicxml_clean/` — Cleaned MusicXML
6. `06.score_info/` — Score header JSON
7. `07.lilypond/` — Full-score LilyPond (symlinked as `transcription.ly`)
8. `08.ly_render/` — Rendered PDF (symlinked as `transcription.pdf`)
9. `09.layout/` — System/measure layout JSON
10. `10.images/` — Cropped system and measure PNGs
11. `11.xml_snippets/` — Per-system and per-measure MusicXML snippets
12. `12.ly_snippets/` — Per-system LilyPond snippets

Phase 2 will add LLM-assisted fixing of the LilyPond snippets.

## Architecture

- `cli.py` — CLI entry point; `new` and `update` subcommands
- `pipeline.py` — Pipeline orchestration; stage definitions and dependency tracking
- `stages.py` — `Stage` enum
- `settings.py` — `ConvertSettings` dataclass (frozen)
- `metadata.py` — `.s2l/score2ly_metadata.json` read/write
- `audiveris.py` — Audiveris subprocess wrapper
- `pdf.py` — PDF utilities (detection, rasterization, OMR PDF building)
- `image_processing.py` — Preprocessing steps (crop, deskew, CLAHE, etc.)
- `musicxml_cleanup.py`, `musicxml_snippets.py`, `musicxml2ly.py` — MusicXML handling
- `omr_layout.py` — Layout extraction from `.omr` files
- `score_info.py` — Score header collection (interactive + OMR-extracted)
- `ly_merge.py`, `lilypond.py` — LilyPond conversion and rendering
- `utils.py` — `relative(path, base)` helper

## Architecture Principles

- Build in **small, reviewable steps** — each increment should be understandable and checkable before moving on.
- Prefer simple, explicit code over clever abstractions.
- CLI is a thin wrapper over the pipeline; pipeline stages are pure functions that yield output paths.
- Stage functions receive only what they need (via closures for input-path injection, not a shared parameter).

## Development Conventions

- One concern per module — keep files small and focused
- Tests live in `tests/`, mirroring the `src/score2ly/` layout
- Don't add docstrings or comments to code that wasn't changed
- Don't over-engineer: build exactly what's needed for the current step
- When asked to commit, include changes done manually, often in other files, often in README.md or .random-notes.md
- **Keep README.md up to date**: any change that affects user-facing behaviour (CLI args, pipeline stages, bundle structure, tools) must be reflected in the README in the same commit

## Tooling & Environment

- **Python 3.12+**, **uv** for environment and dependency management
- **pyproject.toml** for project metadata and dependencies
- **git** for version control; use tags for releases
- External tools: **Audiveris** (OMR), **LilyPond** (rendering)