# Conversation Lab website

From the project root, run `bin/start_practice.ps1` and open
**http://localhost:8765** in Chrome or Edge. Allow microphone access, choose a
conversation, and click Start. Read the question; words turn green as they are
recognized. A relaxed word alignment accepts omissions and minor wording changes.
After a short pause, the answer plays and the next question appears.

**Debug** shows the transcript, coverage, silence timing, events, and matching/pause
controls. The default silence window is 0.8 seconds. **I'm finished** advances a
turn manually. Recognition pauses during answers. Playback follows source order,
and each answer starts only once per attempt. Progress is stored per set in the
browser; a new attempt resets it.

Vignette 1 has one question with two answers (011 and 012), which play together in
order. Optional examples appear as expandable context. Readable prompt overrides
are in `data/question_overrides.json`; original questions remain in the catalog.
Incomplete recording sets are excluded.

## Source and output

```text
bin/site/index.html          Audio library template
bin/site/session.html        Session page template
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
  media/{edited,original,reviewed}/
```

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
