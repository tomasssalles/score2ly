# `score2ly` / Score2LilyPond

Convert musical scores to [LilyPond](https://lilypond.org/) format.

## Supported input formats

- PDF

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

### TODO

- Support for image files (PNG, JPG etc) as input.
- Support for MusicXML as input.
- Suport for LilyPond as input.
- Update command needs --overwrite argument or a new --output/--directory (and then copy all existing artifacts that won't change). Or maybe when not overwriting, pass a --tag argument (e.g. "--tag=v2") or similar and add that to the name to get the new output dir (`<old-stem>.<tag>.s2l`)?
- Add versioning info to metadata? How do we handle versions? Filenames? Bundle directory name? Metadata top-level? Per stage? Maybe we don't handle versioning after all (for now) and the user can handle it via --output if they want?
- Describe the contents of the output file bundle here.
