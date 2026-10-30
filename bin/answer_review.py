"""Independent answer editors: generate a preview, then save those exact WAV bytes.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import partial
import hashlib
from html import escape
import io
import json
from pathlib import Path
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

from filelock import FileLock
import ipywidgets as W
from IPython.display import FileLink
import numpy as np
import soundfile as sf

from answer_tts import MODEL_ID, ROOT, SAMPLE_RATE, VOICES, TTSEngine, load_answers
from speaker_playback import SpeakerPlayback
from project_paths import audio_root

REVIEW_OUTPUT = audio_root('reviewed')

def fingerprint(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preview_audio(engine, settings, *, long_pause=False):
    """Send the exact entered text to the model, without extra processing.
"""
    text = settings['text']
    if not text.strip():
        raise ValueError('Enter some text to read aloud.')
    details = {'rendered_text': text, 'audio_processing': 'none', 'preview_version': 2}
    return engine.synthesize(text, settings['voice'], settings['speed']), details


@dataclass(frozen=True)
class Preview:
    wav_bytes: bytes
    settings: dict
    signature: str
    details: dict
    duration_seconds: float


class ReviewStore:
    """Draft text/settings and deliberately saved individual answer files.
"""
    def __init__(self, output=REVIEW_OUTPUT, project_root=None):
        self.output = Path(output)
        self.project_root = Path(project_root) if project_root is not None else (
            ROOT if self.output.resolve() == REVIEW_OUTPUT.resolve() else self.output)
        self.drafts_path = self.output / 'drafts.json'
        self.portable_path = self.project_root / 'data' / 'answer_edits.json'
        self.drafts = self.read_drafts()

    def read_drafts(self):
        # Either file may have been edited on a different PC or by an older
        # notebook. Merge in modification order so the latest copy wins.
        merged = {}
        paths = [p for p in (self.drafts_path, self.portable_path) if p.exists()]
        for path in sorted(paths, key=lambda p: p.stat().st_mtime_ns):
            merged.update(json.loads(path.read_text(encoding='utf-8')))
        return merged

    @staticmethod
    def key(answer):
        return f'{answer.source}::{answer.index:03d}'

    @staticmethod
    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def update_draft(self, answer, settings):
        self.output.mkdir(parents=True, exist_ok=True)
        # Merge under a lock so the three document notebooks can share drafts.
        with FileLock(str(self.drafts_path) + '.lock', timeout=10):
            latest = self.read_drafts()
            latest[self.key(answer)] = dict(settings)
            self.write_json(self.portable_path, latest)
            self.write_json(self.drafts_path, latest)
            self.drafts = latest

    def export_portable(self):
        """A small source/data archive; excludes environments, models, and audio.
"""
        self.drafts = self.read_drafts()
        self.write_json(self.portable_path, self.drafts)
        names = ['data/answer_edits.json', 'README.md', '.gitignore']
        files = [self.project_root / name for name in names]
        extensions = {'.py', '.ps1', '.txt', '.json', '.html', '.css', '.js', '.mjs', '.md'}
        files.extend(p for p in (self.project_root / 'bin').rglob('*')
                     if p.suffix in extensions and '__pycache__' not in p.parts
                     and 'test-results' not in p.parts)
        files.extend(p for p in (self.project_root / 'notebooks').rglob('*.ipynb')
                     if '.ipynb_checkpoints' not in p.parts)
        files.extend((self.project_root / 'data' / 'scripts').glob('*.docx'))
        files.extend(self.project_root / 'data' / name
                     for name in ('punctuation_overrides.json', 'question_overrides.json'))
        target = self.project_root / 'backups' / 'answer_notebooks_portable.zip'
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.partial.zip')
        with ZipFile(temp, 'w', compression=ZIP_DEFLATED) as archive:
            for path in files:
                if path.is_file():
                    archive.write(path, path.relative_to(self.project_root).as_posix())
        temp.replace(target)
        return target

    def save(self, answer, preview, current_settings, destination=None):
        if preview.signature != fingerprint(current_settings):
            raise ValueError('The text or voice settings changed. Generate a new preview before saving.')
        path = Path(destination) if destination is not None else (
            self.output / Path(answer.source).stem / f'answer_{answer.index:03d}.wav')
        folder = path.parent
        folder.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.partial.wav')
        # Save the exact auditioned file; never synthesize again inside Save.
        temp.write_bytes(preview.wav_bytes)
        temp.replace(path)
        path.with_suffix('.txt').write_text(preview.settings['text'], encoding='utf-8')
        metadata = {'model': MODEL_ID, 'source_answer': asdict(answer), **preview.settings,
                    **preview.details, 'sample_rate': SAMPLE_RATE, 'subtype': 'PCM_24',
                    'duration_seconds': preview.duration_seconds, 'settings_fingerprint': preview.signature,
                    'audio_sha256': hashlib.sha256(preview.wav_bytes).hexdigest(),
                    'saved_utc': datetime.now(timezone.utc).isoformat()}
        self.write_json(path.with_suffix('.json'), metadata)
        self.update_draft(answer, preview.settings)
        return path


class AnswerEditor:
    def __init__(self, studio, answer):
        self.studio, self.answer = studio, answer
        draft = studio.store.drafts.get(studio.store.key(answer), {})
        self._preview = None
        self._busy = False
        self._tasks = set()
        default_text = answer.spoken_text
        self.text = W.Textarea(value=draft.get('text', default_text), description='Text:',
                               layout=W.Layout(width='100%', height='95px' if len(default_text) > 100 else '65px'))
        self.voice = W.Dropdown(options=VOICES, value=draft.get('voice', 'af_heart'), description='Voice:',
                                layout=W.Layout(width='440px'))
        self.speed = W.FloatSlider(value=draft.get('speed', 1.0), min=0.75, max=1.25, step=0.05,
                                   description='Speed:', continuous_update=False, readout_format='.2f',
                                   layout=W.Layout(width='360px'))
        self.generate_button = W.Button(description='Generate preview', icon='play', button_style='info')
        self.play_button = W.Button(description='Play preview', icon='play', button_style='primary', disabled=True)
        self.stop_button = W.Button(description='Stop', icon='stop', disabled=True)
        self.save_button = W.Button(description='Save this preview', icon='save', button_style='success', disabled=True)
        self.reset_button = W.Button(description='Reset text', icon='undo')
        self.status = W.HTML('Generate a preview, then click Play preview or the triangle on the audio player below.')
        # A persistent media widget receives updates even when generation finishes
        # outside the original notebook cell/comm message's output context.
        self.audio_player = W.Audio(value=b'', format='wav', controls=True, autoplay=False,
                                    layout=W.Layout(width='100%', max_width='600px'))
        self.audio_output = W.Output()
        self.saved_output = W.Output()
        self.inputs = [self.text, self.voice, self.speed]
        question = W.HTML(f'<div style="white-space:pre-wrap">{escape(answer.question)}</div>')
        original = W.HTML(f'<div style="white-space:pre-wrap">{escape(answer.raw_answer)}</div>')
        context = W.Accordion(children=[question, original], selected_index=None)
        context.set_title(0, 'Question for context')
        context.set_title(1, 'Original answer')
        advanced = W.Accordion(children=[W.VBox([self.voice, self.speed])],
                               selected_index=None)
        advanced.set_title(0, 'Voice and delivery settings')
        self.widget = W.VBox([
            W.HTML(f'<h4 style="margin:4px 0">Answer {answer.index:03d}</h4>'
                   f'<small>{escape(Path(answer.source).stem)}</small>'), context, self.text,
            advanced, W.HBox([self.generate_button, self.play_button, self.save_button],
                            layout=W.Layout(flex_flow='row wrap')),
            W.HBox([self.stop_button, self.reset_button]),
            self.studio.export_widget,
            W.HBox([self.studio.playback.device, self.studio.playback.test_button],
                   layout=W.Layout(flex_flow='row wrap')),
            self.studio.playback.status,
            self.status, self.audio_player, self.audio_output, self.saved_output,
        ], layout=W.Layout(border='1px solid #ccc', padding='12px', margin='8px 0', max_width='1050px'))
        for control in self.inputs:
            control.observe(self._changed, names='value')
        self.generate_button.on_click(lambda _: self._launch())
        self.play_button.on_click(lambda _: self.play_preview())
        self.stop_button.on_click(lambda _: self.stop_preview())
        self.save_button.on_click(lambda _: self.save_preview())
        self.reset_button.on_click(lambda _: setattr(self.text, 'value', default_text))

    def settings(self):
        return {'text': self.text.value, 'voice': self.voice.value, 'speed': float(self.speed.value),
                'audio_processing': 'none', 'preview_version': 2}

    def _changed(self, _):
        self.studio.store.update_draft(self.answer, self.settings())
        self.save_button.disabled = True
        self.play_button.disabled = True
        self.audio_player.value = b''
        self.status.value = 'Text saved to answer_edits.json. Generate a fresh preview to hear these edits.'

    def _launch(self):
        if self._busy:
            return
        task = asyncio.create_task(self.generate_preview())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def generate_preview(self):
        if self._busy:
            return
        self._busy = True
        self.save_button.disabled = True
        self.play_button.disabled = True
        self.audio_player.value = b''
        self.generate_button.disabled = True
        self.reset_button.disabled = True
        for control in self.inputs:
            control.disabled = True
        settings = self.settings()
        self.status.value = 'Generating this answer on CUDA. The model loads on the first preview.'
        self.audio_output.outputs = ()
        try:
            self.studio.store.update_draft(self.answer, settings)
            loop = asyncio.get_running_loop()
            preview = await loop.run_in_executor(self.studio.executor,
                                                 partial(self.studio.generate, self.answer, settings))
            self.show_preview(preview)
            return preview
        except Exception as exc:
            self.status.value = f'Preview failed: {escape(str(exc))}'
            self.audio_output.append_stderr(traceback.format_exc())
        finally:
            self._busy = False
            self.generate_button.disabled = False
            self.reset_button.disabled = False
            for control in self.inputs:
                control.disabled = False

    def show_preview(self, preview):
        self._preview = preview
        self.audio_player.value = preview.wav_bytes
        current = fingerprint(self.settings()) == preview.signature
        self.play_button.disabled = not current
        self.save_button.disabled = not current
        self.status.value = (f'Preview ready ({preview.duration_seconds:.2f}s). '
                             'Choose your speaker, then click Play preview beside Generate preview.')

    def play_preview(self):
        if self._preview is None or self._preview.signature != fingerprint(self.settings()):
            self.status.value = 'Generate a preview for your current text before playing it.'
            return
        try:
            name = self.studio.play_on_pc(self.answer, self._preview)
            self.stop_button.disabled = False
            self.status.value = 'Playing through ' + escape(name)
        except Exception as exc:
            self.status.value = f'Playback failed: {escape(str(exc))}. Choose another speaker or use the player below.'

    def stop_preview(self):
        self.studio.playback.stop()
        self.stop_button.disabled = True
        self.status.value = 'PC playback stopped. The audio player below has its own pause control.'

    def save_preview(self):
        try:
            if self._preview is None:
                raise ValueError('Generate a preview before saving.')
            path = self.studio.store.save(self.answer, self._preview, self.settings())
            self.status.value = f'Saved answer {self.answer.index:03d}. The saved WAV matches the preview exactly.'
            self.saved_output.outputs = ()
            try:
                link = path.relative_to(Path.cwd())
            except ValueError:
                link = path
            self.saved_output.append_display_data(FileLink(str(link)))
            return path
        except Exception as exc:
            self.status.value = escape(str(exc))
            return None


class AnswerReviewStudio:
    def __init__(self, output=REVIEW_OUTPUT, engine_factory=None, project_root=None):
        self.answers = load_answers()
        self.store = ReviewStore(output, project_root=project_root)
        self.playback = SpeakerPlayback(output)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='answer-review')
        self.engine_factory = engine_factory or self._default_engine
        self.engines = {}
        self.editors = {}
        self.export_button = W.Button(description='Export for another PC', icon='download',
                                      layout=W.Layout(width='220px'))
        self.export_output = W.Output()
        self.export_button.on_click(lambda _: self.export_portable())
        self.export_widget = W.VBox([self.export_button, self.export_output])

    def export_portable(self):
        try:
            for editor in self.editors.values():
                self.store.update_draft(editor.answer, editor.settings())
            path = self.store.export_portable()
            self.export_output.outputs = ()
            try:
                link = path.relative_to(Path.cwd())
            except ValueError:
                link = path
            self.export_output.append_stdout('Your text edits and notebooks are ready to copy to another PC.\n')
            self.export_output.append_display_data(FileLink(str(link)))
            return path
        except Exception as exc:
            self.export_output.append_stderr(str(exc) + '\n')
            return None

    @staticmethod
    def _default_engine(delivery):
        return TTSEngine()

    def answer(self, source, index):
        key = (source, index)
        if key not in self.editors:
            answer = next(a for a in self.answers if (a.source, a.index) == key)
            self.editors[key] = AnswerEditor(self, answer)
        return self.editors[key].widget

    def generate(self, answer, settings):
        delivery = 'original'
        if delivery not in self.engines:
            self.engines[delivery] = self.engine_factory(delivery)
        engine = self.engines[delivery]
        audio, details = preview_audio(engine, settings,
                                      long_pause=any(c.lower() == 'long pause' for c in answer.cues))
        if audio.size == 0 or not np.isfinite(audio).all() or np.max(np.abs(audio)) >= 1:
            raise RuntimeError('Invalid preview audio.')
        stream = io.BytesIO()
        sf.write(stream, audio, SAMPLE_RATE, format='WAV', subtype='PCM_24')
        return Preview(stream.getvalue(), dict(settings), fingerprint(settings), details,
                       round(len(audio)/SAMPLE_RATE, 3))

    def play_on_pc(self, answer, preview):
        return self.playback.play(preview.wav_bytes)
