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
- Document the intended points of human intervention: After stage 3, user can use audiveris to modify the .omr project, save and re-run the pipeline in update mode. After stage 4, user can open the .xml in MuseScore (add a friendly message about installation), make small changes, save and re-run the pipeline in update mode. After stage 7, user can edit the .ly in any text editor, save and re-run the pipeline in update mode. Technically, if the user sees that some of the images from stage 6 are poorly aligned, they could even make their own screenshots from the preprocessed PDF, replace the images with the same name and re-run the pipeline in update mode. 
- Find out where the biggest issues arise and what the best way to fix them is. Apparently musicxml2ly introduces a mess, for example. Though OMR itself already makes many mistakes. Bots could help fix the .ly, or produce it from the .xml, or produce it from the images...


### Big limbo of ideas

- Review this README. A lot is outdated.
- Finalize the update command.
- Run musicxml2ly, merging and rendering anyway before using LLMs (but still use the XML files as inputs for the LLMs)
- Use LLMs in a separate "fix" command
- If no API key provided, still try to fetch from cache before failing, that way "not passing an API key" becomes a safe way to re-run without risking costs or hitting API limits.
- We should include the system prompt in the hash. So the hash would use: system prompt + model + image bytes + xml/ly bytes, and we'd store the cache under ~/.score2ly/cache/<hash>.ly
- I'd like some human-readable way of finding the right cache entry. Maybe some JSONL file where we append dicts with the full path of the bundle, which system, which LLM model, a nanosecond timestamp and the cache entry path. We should also append new entries for cache-hits, i.e. when no new request is made, because the human looking for a cache entry might e.g. try looking for it based on the rough timestamp they remember running the pipeline.
- Gemini suggests I try Gemini 3.1 Pro and Claude 3.7 Sonnet (via OpenRouter/Puter). If the free tier API limits are too low, go for Gemini 2.5 Flash. Offer the user helpful tips on getting API keys with free-tier and which models to use.
- Also use the LLM trick with .png + .ly as input. Then implement the fixing stage in rounds, where each round uses the image plus the last output as the new input.
- After each round of fixing: merge and render.
- Maybe use a ~/.score2ly/config where the user can store a map of LLM models to API keys, as well as a default LLM model.
- Add a final .ly and .pdf render as symlinks and update them when a new fix-round runs.
- We still need to get some very basic header strings from the user (with helpful suggestions/initial values).
- In convert/update, just stop after the musicxml2ly+merging+rendering+symlinking results as best so far. If fix is run without the pipeline being finished, crash. When fix runs the first time, use PNG + XML. After that, each fix will use PNG + latest .ly (never fix from the .ly output from musicxml2ly).
- Whenever .ly files are generated (musicxml2ly, fix round 0, 1, 2, ...) I'd like to merge and render and update the "current best" links in the bundle. But I'm not sure how to handle human intervention (i.e. user manually edits some .ly file, maybe for a single system, maybe one of the merged ones). In that case there should be some updates (e.g. re-merging, re-rendering). But it gets very tricky very fast with these "dynamic stages" of multiple rounds of fixing.
