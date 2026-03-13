# `score2ly` / Score2LilyPond

Convert musical scores to [LilyPond](https://lilypond.org/) format.

## Supported input formats

- PDF
- Image files (PNG, JPG, …)
- MusicXML
- LilyPond (`.ly`)

## Features (planned)

- CLI tool (`score2ly`) and GUI (`Score2LilyPond`)
- Optional AI-assisted OMR improvement (bring your own API key)
- Manual intervention points in the pipeline
- Versioned output artifacts

## Setup

```bash
uv sync
```

## Usage

```bash
# during development
uv run score2ly --help

# after installation
score2ly --help
```

## Status

Early development.