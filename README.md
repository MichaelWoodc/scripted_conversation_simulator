# Scripted conversation simulator

Website: **[Open Conversation Lab](https://michaelwoodc.github.io/scripted_conversation_simulator/)**.
Once GitHub Pages is enabled and these files are pushed, that address automatically
redirects to [the website in `dist/`](https://michaelwoodc.github.io/scripted_conversation_simulator/dist/).

No custom deployment workflow is needed. In the repository's **Settings → Pages**,
choose **Deploy from a branch**, select the branch containing these files, select
**`/(root)`**, and save. Commit the root `index.html`, `.nojekyll`, and the complete
`dist/` folder, including its audio files. The root `.nojekyll` serves the files
directly, preserving the recording paths.

Run `bin/start_practice.ps1` and open **http://localhost:8765** in Chrome or Edge.
Choose a recording edition and vignette. Read each question aloud; recognized words
turn green, and the matching recorded answer plays after a short pause.

Before starting, **Check microphone & device** chooses transcription, voice timing,
or manual practice. Voice timing advances a progress bar while you speak; after
75% of the question's measured TTS duration and a three-second pause, the answer
plays. Debug explains unavailable transcription and lets you adjust the pause and
volume threshold. Use the HTTPS website on phones. The cookie banner lets visitors
choose whether progress is remembered. See [the website guide](bin/site/README.md)
for device checks, question-audio generation, and storage preferences.

The project is organized as follows:

```text
index.html                   Redirect from the GitHub Pages root to dist/
.nojekyll                    Serve the committed files without a Jekyll build
bin/                         Python code, PowerShell launchers, requirements, tests
  site/                      Editable HTML, JavaScript, CSS, and page templates
  project_paths.py           Shared project and audio paths
notebooks/                   Audio editing and notebook generation
  answer_review.ipynb       Combined working notebook
  answers_tts.ipynb          Alternate combined working notebook
  generate_base_notebooks.ipynb
  answers/                   Working notebooks, one per Word script
  generated/                 Generated combined and per-script notebooks
data/                        Word scripts, settings, and reports
  scripts/                   The three original Word scripts
  answer_edits.json          Backup of executed answer text and voice/speed settings
dist/                        Complete website ready to serve or publish
  index.html
  assets/
  sets/
  catalog.json
  media/                     Shared recordings used by notebooks and the website
    edited/
    original/
    reviewed/
backups/                     Archives, exports, and snapshots from before the refactor
```

All `.py` files are under `bin/`. The website application and recordings are under
`dist/`; the root `index.html` redirects visitors there. Edit frontend source in
`bin/site/`, then rebuild; changes made
directly to generated HTML/CSS/JavaScript in `dist/` are overwritten by the build.

## Edit and save recordings

From the project folder:

```powershell
.\bin\setup_tts.ps1
.\bin\start_answer_review.ps1
```

Select the **Answers TTS (CUDA)** kernel and run the notebook setup cell once.
Edit an answer's `text`, `voice`, and `speed` in its code cell. Run that cell to
generate a preview, click **Play preview**, then **Save and replace WAV**.
Run only the answer cells you want to generate. The first preview loads the model.
Choose your **Speaker** and use **Test speaker** to check playback.

Save writes the exact preview you heard directly into the website:

```text
dist/media/edited/
  af_heart/
    speed_1p00/
      Video Vignette 1 MatsProRes Indicated_Streamline Script/
        answer_003.wav
        answer_003.txt
        answer_003.json
```

Voice and speed determine their folders. Each player shows its exact destination.
After editing code, rerun the cell before saving. Saving one answer does not change
another answer's preview or destination. Refresh the browser after saving to load
the latest recording and catalog revision. New complete voice/speed sets appear
after restarting the launcher or rebuilding the site.

Text, punctuation, and line breaks go straight to the model. No audio effects are
applied. Output is native 24 kHz, 24-bit PCM WAV. The default voice is Heart
(`af_heart`), using local Kokoro-82M on CUDA. Combined tracks are batch outputs.

**Ctrl+S saves your text inside the notebook.** Running an answer cell also backs
up its text and settings in `data/answer_edits.json`.

To generate fresh base notebooks from the Word scripts, open
`notebooks/generate_base_notebooks.ipynb` and Run All. It reads `data/scripts/` and
writes to `notebooks/generated/`, preserving existing answer-cell edits by default.
The generator itself does not load a speech model or generate audio. The generated
notebooks use the same `dist/media/edited/` Save destination as the working notebooks.

## Serve or publish the website

```powershell
.\bin\start_practice.ps1
# Or rebuild without starting a server:
python .\bin\build_site.py --static
# Serve the complete static output directly:
python -m http.server 8765 --directory dist
```

For GitHub Pages, publish the repository branch from **`/(root)`** as described
above. The root page redirects to `dist/`. For another static host, you can publish
the **contents of `dist/`**, including `media/`, directly. Every build uses the same
recordings that the notebooks save; no separate audio export or copy is required.
Rebuild after adding new complete recording sets. Use localhost or HTTPS for
microphone access. See [the website notes](bin/site/README.md) for browser behavior.

## Move to another PC

Save the notebook before clicking **Export for another PC**. This creates
`backups/answer_notebooks_portable.zip`, preserving the `bin/`, `notebooks/`, and
`data/` layout. It includes supporting source/templates, requirements, text backups,
and Word scripts. Copy `dist/media/` separately to retain existing recordings.
Installed environments and model downloads are excluded.

Extract the archive, open Anaconda PowerShell Prompt in the extracted project, and
run `bin/setup_tts.ps1`, followed by `bin/start_answer_review.ps1`. Use
`bin/setup_tts.ps1 -TextOnly` to edit and export without a GPU. Notebook code cells
preserve your latest saved text; `data/answer_edits.json` backs up executed text.

## Environment and batch generation

`bin/setup_tts.ps1` creates `.conda-tts/` at the project root with Python 3.11,
PyTorch 2.7.1/CUDA 12.6, and `bin/requirements-tts.txt`. It registers the notebook
kernel and verifies GPU computation. Models are cached in `.cache/huggingface/`.
`bin/requirements-tts-lock.txt` records the installed package versions.

```powershell
.\bin\generate_audio.ps1
.\bin\generate_audio.ps1 -EmphasizedPunctuation
```

Batch generation reads the Word scripts, optionally applying punctuation presets.
It writes directly to `dist/media/original/` or `dist/media/edited/` and resumes
matching completed clips. Logs and status files live in that edition's folder.
Batch generation uses Word text; use the notebooks to generate your code-cell edits.
The three Word files contain 109 answers (38, 28, and 43); questions are never narrated.

Run regression checks with the TTS environment active:

```powershell
python -m unittest discover -s bin -p 'test_*.py'
cd bin
npm test
```

Model and voices: [Kokoro](https://github.com/hexgrad/kokoro),
[voice catalog](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).
