# Conversation Lab website

From the project root, run `bin/start_practice.ps1` and open
**http://localhost:8765** in Chrome or Edge. Choose a conversation, then click
**Check microphone & device** on the separate setup screen. Options are ordered
Transcription, Timing based, Manual. The best working option is green; unavailable
options are red with permission/retry buttons beside them. Continue to enter the
session. The optional settings cookie remembers your mode, pause, and volume
threshold so you skip setup next time. **Change mode** reopens setup, and a known
missing microphone permission brings setup back automatically.

The compact setup includes a microphone check: any recognized speech enables
transcription and highlights detected words, while voice timing fills a
one-second speech bar. The setup preview keeps the latest recognized words.
Both cards have a volume-threshold slider and live input level. With storage
consent (or the explicit remember checkbox), verified capability results survive
reloads in the settings cookie. Temporary audio suspension does not erase a
passed test. The skip-setup checkbox remains a separate choice.

The check tests microphone access,
volume monitoring, WAV playback, and whether the transcription service starts.
Debug shows the active microphone, reported input sample rate, available browser
APIs, selected mode, and the reason for any fallback. No camera or unrelated
hardware is requested.

Automatic mode uses word highlighting when transcription works. If its API is
absent, its service fails, or it detects sustained speech without returning words,
practice switches to **Voice timing**. Only time above the microphone volume
threshold fills the bar. Once it reaches 50% of the question recording's duration,
a 2.5-second pause plays the answer. Debug lets visitors adjust that pause
(1.5–5 seconds) and microphone sensitivity. Voice timing estimates reading time;
it does not check which words were spoken. A manual mode remains available if the
microphone cannot be used. Visitors can also select voice timing or manual mode
before the device check.

**Debug** shows the transcript, coverage, silence timing, events, and matching/pause
controls. The transcription silence window is 0.8 seconds. **I'm finished** advances a
turn manually. Recognition pauses during answers. Playback follows source order,
and each answer starts only once per attempt. Progress is stored per set in the
browser only after consent; a new attempt resets it. Question previews pause
listening so their audio never fills the speaking-time bar.

On a phone, use the published **HTTPS** address. Opening an HTTP LAN address for
your desktop does not provide a secure microphone context. If the browser blocks
automatic audio, **Play this answer** lets the visitor resume with a tap.

and late results from an older recognizer are ignored.
Phone transcription uses short recognition sessions and gives the native speech
service exclusive microphone access. It does not open a competing Web Audio
volume stream or play/pause a silent audio clip at transcription startup. The
Timing test checks volume separately. Transcription keeps retrying through empty
recognition sessions until speech is detected or the visitor pauses. Debug includes
the browser and actual speech-service error. Late results from an older recognizer
are ignored.

## Question audio and consent

Run `python bin/generate_question_audio.py` on Windows after changing questions.
It uses the installed Microsoft Zira Desktop voice to synthesize each unique
prompt into `dist/media/questions/`, reuses existing WAVs, and rebuilds the site.
Use `--force` to regenerate all question recordings. Durations in the catalog
come from actual WAV frame counts; the **Hear this question** button previews
them. The published site needs no visitor-side TTS service or model. A newly
added question without a recording retains the manual finish control.

The cookie banner offers **Remember my progress** and **Session only**. Until
acceptance, progress and preferences stay in page memory; optional local storage
is neither read nor written. One essential consent cookie remembers the choice.
The footer reopens preferences, and switching to Session only clears this app's
saved local-storage entries. No advertising or analytics cookies are used.

Vignette 1 has one question with two answers (011 and 012), which play together in
order. Optional examples appear as expandable context. Readable prompt overrides
are in `data/question_overrides.json`; original questions remain in the catalog.
Incomplete recording sets are excluded.

## Source and output

```text
bin/site/index.html          Audio library template
bin/site/session.html        Session page template
bin/site/setup.html          Intermediary device and mode selection screen
bin/site/assets/             Editable JavaScript and CSS
bin/build_site.py            DOCX/audio validation and site build
bin/server.py                Local server with fresh catalogs and audio range requests
bin/tests/                   Python and JavaScript regression tests
data/scripts/                Source Word scripts
data/question_overrides.json
dist/                        Entire website, ready for static hosting
  assets/
  sets/
  catalog.json
  media/{edited,original,reviewed,questions}/
```

All page markup lives in the HTML templates, including session cards, question
words, and button contents. The build writes that markup directly into every
`dist/*.html` and `dist/sets/*.html` page. JavaScript handles edition filtering,
progress, speech recognition, and playback using those existing elements.

Restart the launcher after changing frontend source, or run
`python bin/build_site.py --static`. For GitHub Pages, select **Deploy from a
branch → your branch → `/(root)`**. Commit the root `index.html`, `.nojekyll`, and
the complete `dist/` folder, including `media/`. No custom workflow is required.
[The public URL](https://michaelwoodc.github.io/scripted_conversation_simulator/)
automatically redirects to
[`dist/`](https://michaelwoodc.github.io/scripted_conversation_simulator/dist/).
For another static host, you can publish the **contents of `dist/`** directly.
All asset and audio URLs are relative, so repository subpaths work. No API server,
model, or API key is required for the published website. Use HTTPS or localhost
for microphone access.

The notebooks save directly into `dist/media/edited/<voice>/speed_1p00/<Word filename>/`.
Batch generation uses the same layout under `original/` or `edited/`. The website
build reads these files in place, so every build is self-contained. Refresh after
replacing an existing recording; rebuild to add pages for new complete sets. For
static hosting you can also run `python -m http.server 8765 --directory dist`.

## Recognition

Web Speech API supplies interim results through the browser's recognition service,
which may need internet access. The application does not store microphone audio
or transcripts. Permissions, service behavior, network latency, and accent affect
matching. This is word alignment rather than semantic grading.

The adapter in `bin/site/assets/speech.js` isolates recognition for future changes.

## All answer speakers

The library and session Settings link to `voice-samples.html`, where every Kokoro
voice reads "The quick brown fox jumps over the lazy dog." Search by name, ID,
or training language. Only one sample plays at a time. Samples are independent of
full answer-set generation. Regenerate them with
`.cache/answer-voices-env/Scripts/python.exe bin/generate_voice_samples.py`.

`notebooks/generate_all_answer_voices.ipynb` creates every speaker in the Kokoro
voice pack. Heart remains the default answer voice and existing Heart recordings
are preserved. Question previews are generated separately with Bella. Packages
and model downloads are isolated under `.cache/`. The job can be restarted to
resume partial work, and it rebuilds the site after each completed voice.

Session **Settings** offers the answer-speaker selector. Only complete, compatible
recording sets can be selected; pending speakers unlock after generation and a
page refresh. The library keeps one card per conversation rather than duplicating
cards for each speaker. Speaking-time controls sit at the bottom of the question:
volume threshold, required percentage (default 50%), and a 1?5 second silence
slider (default 2.5 seconds). Sliders show their numeric values immediately.

Bulk response text comes from the six Excel workbooks in `data/responses/`.
Edit the `response` column and use Alt+Enter for newlines. Text is read directly
without adding pauses or silence. Save before rerunning the notebook. Set
`UPDATE_HEART = True` there if the edits should replace Heart's recordings too.
