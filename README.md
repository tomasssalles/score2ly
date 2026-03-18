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
- If a pipeline stage actually generates a new artifact, it needs to force the subsequent stages to run. Cleanest would be for update_stage to delete the entries for higher stages. And every stage must then be aware that even if no metadata is available, there might be artifacts present already. Would deleting just the checksum be better?
- The checks for whether a stage should run are wrong. If the checksum doesn't match, we don't want to rerun. It most likely means the user edited the data manually into the new version they wanted. So we want to keep that, update the metadata with the new checksum (probably add a flag saying "externally modified" or such) and then run the subsequent stages starting from this new version. We should probably also either require the user to explicitly state that they intentionally modified the file (and which file) and want to re-run the rest of the pipeline from it (via some CLI arg), or if that's missing, interactively ask the user whether that's the case when we find a checksum mismatch. Of course, in the other situation where there's no metadata for a stage, or there is metadata but the output file doesn't exist, we do want to recompute that stage itself and the subsequent ones, and we don't need to require any CLI args for that or ask the user anything, just log what we're doing.
- In stage 3, the internal format audiveris project data should either be part of the output (simpler) or we should immediately extract all of the information we want about bounding boxes on the images and save that information somewhere as part of the output (and then we can delete the audiveris project).
- Note to self: The extraction from audiveris is horrible, with loads of mistakes even from very good scans. Fixing the mistakes manually in audiveris is horribly horrible and no one wants to do that. But the good news is audiveris seems to correctly identify systems and measures, so we probably won't get mistakes of the kind "this one note was detected with only half of its correct duration and now the rest of the score is completely misaligned". This means it should be easy-ish to fix mistakes later, hopefully. Let's just get to the point where an LLM can help as soon as possible, as that will probably be the biggest win. Also, text extraction from audiveris is horrendously horrific, and even in good scans of relatively modern editions, the text in the header is often... creatively typeset, so even opus 4.6 is struggling. I can still try and see how well gpt-5.1 does, but honestly for the purposes of this project (getting the score in lilypond notation), we don't need perfect text extraction. We could just ask the user for a title, an optional composer, an optional official identifier, an optional edition and an optional comment, and in order to fill in those values we can offer the user the text our best LLM was able to extract (so they can copy/paste parts of it if they want). The lilypond score doesn't have to have the whole text content of the original, certainly not in the same positions or fonts etc. The user already has the original if they just want a PDF to read directly. The purpose of using score2ly is to have a machine-friendly version for further processing.
