# MarkItDown Batch Conversion System

A ready-to-run wrapper around Microsoft's [MarkItDown](https://github.com/microsoft/markitdown)
that converts **any file or an entire folder tree** of mixed file types into
Markdown. Comes in two forms:

- **`gui.py`** — a point-and-click desktop app (no command line needed)
- **`convert.py`** — a command-line version with the same engine, for scripting/automation

## What it handles

Anything MarkItDown supports: PDF, Word, PowerPoint, Excel, images (EXIF +
OCR), audio (EXIF + speech transcription), HTML, CSV/JSON/XML, ZIP archives
(recurses into contents), EPUB, and YouTube URLs. Unknown/binary types are
skipped automatically rather than crashing the run.

## 1. Install

```bash
pip install 'markitdown[all]'
```

Only need a few formats? Install narrower:
```bash
pip install 'markitdown[pdf,docx,pptx,xlsx]'
```

## 2. Run the GUI (recommended for most people)

```bash
python gui.py
```

A window opens with:
- **Choose File... / Choose Folder...** — pick what to convert
- **Save to...** — pick the output folder (defaults to `./output`)
- Checkboxes for skipping already-converted files, enabling plugins, and
  LLM image descriptions
- A **Convert** button, a progress bar, and a live log

On Windows and Mac, `tkinter` (the GUI toolkit) ships with the standard
Python installer, so nothing extra is needed. On Linux you may need:
```bash
sudo apt-get install python3-tk
```

## 3. Or run it from the command line

**Convert one file:**
```bash
python convert.py path/to/file.pdf
```
(writes to `./output/file.md` by default)

**Convert an entire folder, recursively, mirroring its structure:**
```bash
python convert.py path/to/folder -o output
```

**See what would happen first, without writing anything:**
```bash
python convert.py path/to/folder --dry-run
```

**Re-run later and only convert new files:**
```bash
python convert.py path/to/folder -o output --skip-existing
```

**Save a JSON log of every result (useful for large batches):**
```bash
python convert.py path/to/folder -o output --log run.log
```

## 4. Optional upgrades

**LLM-generated image descriptions** (for images and PowerPoint slides):
```bash
export OPENAI_API_KEY=sk-...
pip install openai
python convert.py folder -o output --llm-images --llm-model gpt-4o
```

**Azure Document Intelligence** (higher-fidelity PDF/scan extraction):
```bash
python convert.py file.pdf -o output --docintel-endpoint https://<resource>.cognitiveservices.azure.com/
```

**Azure Content Understanding** (docs + audio + video + structured field
extraction as YAML front matter):
```bash
python convert.py folder -o output --cu-endpoint https://<resource>.cognitiveservices.azure.com/
```

**MarkItDown plugins** (e.g. the `markitdown-ocr` plugin, which adds OCR to
embedded images inside PDF/DOCX/PPTX/XLSX using the same `llm_client`):
```bash
pip install markitdown-ocr
python convert.py folder -o output --use-plugins --llm-images
```

## All options

| Flag | Purpose |
|---|---|
| `-o, --output` | Output directory (default `./output`) |
| `--skip-existing` | Don't reconvert files whose `.md` already exists |
| `--use-plugins` | Enable installed MarkItDown plugins |
| `--workers N` | Parallel threads (default 4) |
| `--exclude-ext .foo .bar` | Extra extensions to skip |
| `--dry-run` | Preview only, no writes |
| `--log path.json` | Write a machine-readable run log |
| `--llm-images` | Use an LLM to describe images/slide images |
| `--llm-model` | Model for `--llm-images` (default `gpt-4o`) |
| `--docintel-endpoint` | Azure Document Intelligence endpoint |
| `--cu-endpoint` | Azure Content Understanding endpoint |

## Notes on safety

MarkItDown reads files with the same privileges as the process running it —
same as `open()`. Don't point this at untrusted input (e.g. user-uploaded
files on a server) without validating paths first. See MarkItDown's own
[Security Considerations](https://github.com/microsoft/markitdown#security-considerations)
for details.
