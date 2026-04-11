# score2ly

Convert a scanned or digital musical score (PDF) into [LilyPond](https://lilypond.org/) format.

score2ly runs an OMR (optical music recognition) pipeline on your PDF using [Audiveris](https://github.com/Audiveris/audiveris), cleans and converts the result to LilyPond, and stores every intermediate artifact in a versioned output bundle (`.s2l` directory). You can inspect and manually correct any artifact, then resume the pipeline from that point.

---

## Requirements

- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**
- **[Audiveris](https://github.com/Audiveris/audiveris/releases)** — OMR engine (must be on `PATH` or set `AUDIVERIS_PATH`)
- **[LilyPond](https://lilypond.org/download.html)** — music engraver (must be on `PATH`)

score2ly checks for these tools at startup and will tell you how to install them if they are missing.

> **Note:** There is an apparently fraudulent site at `audiveris.com`. Install Audiveris only from the [official GitHub releases](https://github.com/Audiveris/audiveris/releases).

---

## Installation

```bash
git clone https://github.com/tomasssalles/score2ly.git
cd score2ly
uv tool install .
```

### Updating

```bash
git pull
uv tool install --reinstall .
```

---

## Quick start

```bash
score2ly new myscore.pdf
```

This creates `myscore.s2l/` next to your PDF and runs the full pipeline. At the end you will have a LilyPond file and a rendered PDF in the bundle.

---

## How it works

### The pipeline

score2ly runs a sequence of stages. Each stage reads the outputs of earlier stages and writes its own outputs into a numbered subdirectory of the bundle. Stages that are already complete are automatically skipped, so you can stop and resume at any point.

| # | Directory | What it contains                                                                                |
|---|-----------|-------------------------------------------------------------------------------------------------|
| 1 | `01.original/` | A copy of your input PDF (or the extracted page range, if `--page-range` was used)              |
| 2 | `02.pages/` | One PNG per page, rasterized from the PDF, with optional preprocessing applied                  |
| 3 | `03.audiveris_omr/` | Audiveris `.omr` project files — one for the full score (`book.omr`) and one per page           |
| 4 | `04.musicxml/` | MusicXML exported from the Audiveris book project (or a MusicXML file you provided via `--xml`) |
| 5 | `05.musicxml_clean/` | MusicXML with layout and style noise stripped out                                               |
| 6 | `06.score_info/` | Score header metadata (title, composer, etc.) in JSON format                                    |
| 7 | `07.lilypond/` | The full-score LilyPond file generated from the clean MusicXML, with corrected header fields    |
| 8 | `08.ly_render/` | A PDF rendered from the full-score LilyPond file                                                |
| 9 | `09.layout/` | JSON layout data: which measures appear in which system on which page, with pixel coordinates   |
| 10 | `10.images/` | Cropped PNG images of each system and each individual measure                                   |
| 11 | `11.xml_snippets/` | Per-system and per-measure MusicXML snippets                                                    |
| 12 | `12.ly_snippets/` | Per-system LilyPond snippets                                                    |

The bundle also contains `score2ly_metadata.json`, which records the original command, input file path, and the state of every completed stage (outputs and checksums). This is how the pipeline detects what needs to re-run after you make manual edits.

Finally, the bundle contains the files `transcription.ly` and `transcription.pdf`, which are the true outputs of the pipeline and what you're actually interested in. The subdirectories with stage artifacts are just for inspection and potentially manual intervention to help improve these final outcomes.

### Dependency tracking

When you edit a file inside the bundle, score2ly detects the change via checksums on the next `update` run and automatically re-runs all downstream stages. You do not need to tell it what changed.

---

## Score information

The LilyPond header (title, composer, etc.) is collected interactively when you first run `new`. score2ly tries to extract values from the MusicXML, but OMR software is generally poor at reading headers, so treat those suggestions with scepticism. You will be prompted to confirm or override each field.

To skip the interactive prompts:

```bash
score2ly new myscore.pdf --no-prompt
score2ly new myscore.pdf --title "Sonata in C" --composer "Haydn" --no-prompt
```

Use `-` to leave a field blank:

```bash
score2ly new myscore.pdf --tagline "-"
```

To correct the score info later, edit `06.score_info/score_info.json` directly in a text editor, then run `score2ly update myscore.s2l`. The LilyPond file and rendered PDF will be regenerated.

---

## Manual intervention

OMR is imperfect. score2ly is designed to allow you to inspect intermediate results and correct them when needed. After editing anything inside the bundle, run:

```bash
score2ly update myscore.s2l
```

This re-runs only the stages whose inputs have changed.

> **Warning:** The stage output directories are numbered for your convenience. If you modify the files in stage N, the next `update` run will recompute all stages M > N that depend on the outputs from stage N. This means any work you've done manually improving stages M > N could be overwritten! If you're going to manually intervene and call `update`, do so one stage at a time, always running `update` in between, and work your way through the stages in the right order.

### What you can edit and with which tools

**Page images (`02.pages/`)** — Rasterized PNGs of each page. Edit these if the built-in preprocessing did not produce good results (e.g. borders not removed, page not straight). Here are some tools you could use for this:

- [Krita](https://krita.org/) — free, powerful, user-friendly
- [Photopea](https://www.photopea.com/) — free, browser-based, good for occasional use
- [GIMP](https://www.gimp.org/) — powerful but steep learning curve

**Audiveris OMR projects (`03.audiveris_omr/`)** — The raw OMR data. The `book.omr` file is what the MusicXML export is based on. Editing `.omr` files requires the Audiveris GUI, which is not particularly user-friendly. For most users it is easier to skip this and fix the MusicXML instead.

Note: there are two kinds of `.omr` files — one per page (used for layout/coordinate extraction) and one for the full score (`book.omr`, used for MusicXML export).

**MusicXML (`04.musicxml/`)** — The raw transcription. This is often the most productive place to fix OMR errors.

- [MuseScore](https://musescore.org/) — free, excellent notation editor; open the `.xml` file, correct it visually, then re-export as MusicXML (File → Export)
- Any text editor — for small targeted fixes

Alternatively, if you have access to better OMR software (e.g. [SmartScore](https://www.musitek.com/), [PlayScore 2](https://www.playscore.co/about-playscore-2/), or a web-based service), use `--xml` to bring your own export:

```bash
score2ly update myscore.s2l --xml my_better_export.xml
```

**Score info (`06.score_info/score_info.json`)** — Edit directly in any text editor.

**Full-score LilyPond (`07.lilypond/`)** — The LilyPond source. Editing this gives you a new rendered PDF immediately on the next `update`. Use [Frescobaldi](https://www.frescobaldi.org/) for a dedicated LilyPond editing experience with live preview.

**Cropped images (`10.images/`)** — Per-system and per-measure PNG crops. These are used as visual reference for the LLM-assisted fixing stage (not included yet, coming in Phase 2). Edit with any image editor (as suggested above for the **Page images**) if the automatic cropping missed something.

**LilyPond snippets (`12.ly_snippets/`)** — Per-system and per-measure LilyPond files. These will be the primary input for LLM-assisted fixing in Phase 2. Edit with [Frescobaldi](https://www.frescobaldi.org/) or any text editor.

---

## Preprocessing (for scanned PDFs)

If your input is a scan rather than a born-digital PDF, Audiveris OMR accuracy depends heavily on image quality. score2ly can apply preprocessing steps to the page images before OMR.

score2ly detects automatically whether a PDF is a scan or vector, but you can override this with `--pdf-kind scan` or `--pdf-kind vector`.

### Available steps

| Argument | What it does                                          | When to use it |
|----------|-------------------------------------------------------|----------------|
| `--sheet-method cc` | Crop to the main sheet (connected-components)         | Page has a dark or coloured border/background |
| `--sheet-method flood_fill` | Crop to the main sheet (flood-fill from corners)      | Page has a distinct background that touches all edges |
| `--sheet-method largest_contour` | Crop to the main sheet (largest contour)              | Page has a rectangular border to remove |
| `--block-method contour` | Crop to the music block (contour detection)           | Significant non-musical areas (titles, margins) confuse OMR |
| `--block-method projection` | Crop to the music block (ink-projection)              | Dense but well-separated music area |
| `--background-normalize` | Divide each pixel by a blurred background estimate, flattening uneven illumination | Ghost ink or faint bleed-through from the reverse side of the page |
| `--background-normalize-kernel F` | Kernel size as a fraction of page width for background estimation (default 0.1) | Fine-tune `--background-normalize` |
| `--trunc-threshold` | Set all pixels at or above a value to white (ceiling) | Ghost ink or faint bleed-through from the reverse side of the page |
| `--trunc-threshold-value V` | Pixel ceiling value for `--trunc-threshold` (default 200, range 0–255) | Fine-tune `--trunc-threshold` |
| `--gamma-correction` | Push mid-range grays toward white (gamma curve)       | Ghost ink or faint bleed-through from the reverse side of the page |
| `--gamma G` | Gamma value for `--gamma-correction` (default 2.0, suggested range 1.5–3.0) | Fine-tune `--gamma-correction` |
| `--deskew` | Straighten slightly rotated pages                     | Scan was placed at a slight angle |
| `--tight-crop` | Remove remaining whitespace after other steps         | Extra margin remaining after other crops |
| `--clahe` | Enhance local contrast                                | Low-contrast, faded, or uneven scan |
| `--projection-k K` | Ink threshold sensitivity for projection block-method | Fine-tune `--block-method projection` |
| `--projection-denoise` | Morphological denoising in projection block-method    | Noisy scan produces fragmented ink regions |

Preprocessing is only applied to the page PNGs (`02.pages/`), not to the original PDF. If results are not satisfactory, you can edit the PNGs directly (see [Manual intervention](#manual-intervention)).

> **Note:** These preprocessing methods are not AI-based and different ones work to a different degree depending on the kind of scan you provide. If you use any of these arguments, be sure to look at the artifacts in `02.pages/` and check whether the desired effect was achieved.

---

## Bring your own MusicXML

If you have a better MusicXML than Audiveris produces — from a dedicated OMR application, a web service, or manual entry — you can inject it into the pipeline:

```bash
# At the start of a new conversion
score2ly new myscore.pdf --xml export_from_musescore.xml

# Or later, to replace a previous export
score2ly update myscore.s2l --xml export_from_musescore.xml
```

When `--xml` is used, the MusicXML export stage is skipped and your file is used instead. Audiveris still runs to extract layout and coordinate data (the `.omr` files are still needed for the system/measure crops).

---

## Page ranges

To convert only a subset of pages — for example, if your PDF contains front matter, or you want to process one movement at a time:

```bash
score2ly new myscore.pdf --page-range 5-9
```

Pages are 1-indexed. Only the selected pages are stored in the bundle; the rest of the PDF is not retained.

---

## CLI reference

### Global options

```
-v, --verbose    Enable debug logging
--version        Show version and exit
```

### `score2ly new INPUT_PDF`

Start a new conversion project. Creates a `.s2l` bundle and runs the full pipeline.

```
INPUT_PDF                     Input PDF file

-o, --output PATH             Output bundle path (must end in .s2l)
-d, --directory DIR           Parent directory for the bundle (name derived from PDF filename)
--overwrite                   Overwrite an existing bundle without prompting

--page-range START-END        Only convert pages START through END (1-indexed, inclusive)
--xml FILE                    Use this MusicXML file instead of running Audiveris export
```

**Score information:**
```
--title TEXT
--subtitle TEXT
--composer TEXT
--work-number TEXT            E.g. "Op. 45", "BWV 772", "K. 331"
--copyright TEXT
--tagline TEXT
--no-prompt                   Skip interactive prompts; use OMR-extracted values and CLI args
```

Use `-` as the value for any score information field to leave it blank.

**Advanced (preprocessing):**
```
--pdf-kind {auto,vector,scan}
--sheet-method {none,cc,flood_fill,largest_contour}
--block-method {none,contour,projection}
--background-normalize
--background-normalize-kernel F
--trunc-threshold
--trunc-threshold-value V
--gamma-correction
--gamma G
--deskew
--tight-crop
--clahe
--projection-k K
--projection-denoise
```

### `score2ly update BUNDLE`

Resume the pipeline from an existing `.s2l` bundle. Re-runs only the stages whose inputs have changed since the last run.

```
BUNDLE                        Path to the .s2l bundle directory

--xml FILE                    Replace the MusicXML export with this file and re-run downstream stages
```

> **Note:** All score information and advanced preprocessing arguments from `new` are also accepted in `update`, but will be silently ignored if the relevant stage has already completed and its inputs have not changed.

---

## External tools

### Audiveris

score2ly uses Audiveris as its OMR engine. Install it from the [official GitHub releases](https://github.com/Audiveris/audiveris/releases) and ensure the `audiveris` command is available on your `PATH`. Alternatively, set the `AUDIVERIS_PATH` environment variable to the full path of the executable.

### LilyPond

score2ly uses LilyPond to render the final transcription to PDF, and also for all MusicXML -> LilyPond conversions (via `musicxml2ly`). Install it from [lilypond.org](https://lilypond.org/download.html) and ensure `lilypond` and `musicxml2ly` are on your `PATH`.

---

## Known limitations and future work

### Multiple movements

MusicXML scores with multiple movements are not yet supported. Audiveris exports each movement as a separate file (`score.mvt1.xml`, `score.mvt2.xml`, …), and score2ly currently requires a single file.

**Workaround:** Process each movement separately using `--page-range` to isolate the relevant pages, and if needed edit the page PNGs manually to remove any overlap.

### GUI

A graphical interface (`Score2LilyPond`) is planned but not yet implemented.

### Fixing OMR mistakes with LLMs (Phase 2 of the project)

This is the main goal of the project and what could one day make it one of the best, affordable ways to transcribe score PDFs into LilyPond format. As you may have noticed, the pipeline already produces some artifacts that are currently not used for the final `transcription.ly` and `transcription.pdf` outputs, such as cropped PNGs of each individual system and short LilyPond snippets of each individual system. These artifacts are meant to be given to a frontier LLM to revise and improve, and in the end the (future) pipeline will combine the results into a final LilyPond source for the full score.
