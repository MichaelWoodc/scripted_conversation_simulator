"""Raw notebook text cells with playback and explicit replacement of answer WAVs.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from html import escape
import io
from pathlib import Path
import traceback

import ipywidgets as W
from IPython.display import FileLink, display
import numpy as np
import soundfile as sf

from answer_review import Preview, ReviewStore, fingerprint, preview_audio
from answer_tts import ROOT, SAMPLE_RATE, TTSEngine, VOICES, load_answers
from speaker_playback import SpeakerPlayback
from project_paths import answer_directory, audio_root


class AnswerPlaybackPanel:
    """Captures this cell run's audio and settings; contains no text editor.
"""
    def __init__(self, studio, answer, settings, preview=None):
        self.studio = studio
        self.answer = answer
        self.settings = dict(settings)
        self.preview = None
        self.target = studio.output_path(answer, settings['voice'], settings['speed'])
        self.play_button = W.Button(description='Play preview', icon='play', button_style='primary', disabled=True)
        self.save_button = W.Button(description='Save and replace WAV', icon='save', button_style='success', disabled=True,
                                     layout=W.Layout(width='200px'))
        self.stop_button = W.Button(description='Stop', icon='stop')
        self.player = W.Audio(value=b'', format='wav', controls=True, autoplay=False,
                              layout=W.Layout(width='100%', max_width='650px'))
        self.status = W.HTML('Run this answer\'s code cell to generate its preview.')
        self.messages = W.Output()
        relative = self.target.relative_to(studio.project_root)
        self.widget = W.VBox([
            W.HTML(f'<b>Answer {answer.index:03d}</b> &mdash; {escape(Path(answer.source).stem)}'),
            W.HBox([self.play_button, self.save_button, self.stop_button],
                   layout=W.Layout(flex_flow='row wrap')),
            self.status, self.player,
            W.HTML(f'<small>Save replaces: <code>{escape(str(relative))}</code></small>'),
            W.HBox([studio.playback.device, studio.playback.test_button],
                   layout=W.Layout(flex_flow='row wrap')),
            studio.playback.status, self.messages,
        ], layout=W.Layout(border='1px solid #ccc', padding='12px', max_width='1050px'))
        self.play_button.on_click(lambda _: self.play())
        self.save_button.on_click(lambda _: self.save())
        self.stop_button.on_click(lambda _: studio.playback.stop())
        if preview is not None:
            self.show_preview(preview)

    def show_preview(self, preview):
        if preview.signature != fingerprint(self.settings):
            return
        self.preview = preview
        self.player.value = preview.wav_bytes
        self.play_button.disabled = False
        self.save_button.disabled = False
        self.status.value = (f'Preview ready ({preview.duration_seconds:.2f}s). Play to listen; Save replaces the file below. '
                             'After editing the code, rerun the cell before saving.')

    def play(self):
        if self.preview is None:
            return
        try:
            name = self.studio.playback.play(self.preview.wav_bytes)
            self.status.value = 'Playing through ' + escape(name)
        except Exception as exc:
            self.status.value = f'Playback failed: {escape(str(exc))}. Choose another speaker or use the player.'

    def save(self):
        if self.preview is None:
            self.status.value = 'Run the code cell to generate a preview first.'
            return None
        if self.studio.panels.get((self.answer.source, self.answer.index)) is not self:
            self.status.value = 'This cell was rerun. Use Save on its newest preview.'
            return None
        try:
            path = self.studio.store.save(self.answer, self.preview, self.settings, destination=self.target)
            self.messages.outputs = ()
            self.messages.append_display_data(FileLink(str(path.relative_to(self.studio.project_root))))
            self.status.value = 'Saved. The numbered WAV was replaced with the exact preview you heard.'
            return path
        except Exception as exc:
            self.status.value = 'Save failed: ' + escape(str(exc))
            return None


class CellAnswerStudio:
    def __init__(self, project_root=ROOT, engine_factory=None, answers=None):
        self.project_root = Path(project_root)
        self.answers = answers if answers is not None else load_answers(self.project_root / 'data' / 'scripts')
        self.store = ReviewStore(audio_root('reviewed', self.project_root), project_root=self.project_root)
        self.playback = SpeakerPlayback(self.store.output)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cell-answer-tts')
        self.engine_factory = engine_factory or (lambda _: TTSEngine())
        self.engines = {}
        self.panels = {}
        self.export_button = W.Button(description='Export for another PC', icon='download',
                                      layout=W.Layout(width='220px'))
        self.export_output = W.Output()
        self.export_button.on_click(lambda _: self.export_portable())
        self.export_widget = W.VBox([self.export_button, self.export_output])

    def find_answer(self, source, index):
        return next(a for a in self.answers if a.source == source and a.index == index)

    def output_path(self, answer, voice, speed):
        if voice not in {v for _, v in VOICES}:
            raise ValueError(f'Unknown voice: {voice}')
        if not 0.7 <= float(speed) <= 1.3:
            raise ValueError('Speed must be between 0.7 and 1.3.')
        return (answer_directory(answer.source, voice, speed, project_root=self.project_root) /
                f'answer_{answer.index:03d}.wav')

    def generate(self, settings):
        if 'original' not in self.engines:
            self.engines['original'] = self.engine_factory('original')
        audio, details = preview_audio(self.engines['original'], settings)
        if not audio.size or not np.isfinite(audio).all() or np.max(np.abs(audio)) >= 1:
            raise RuntimeError('Invalid preview audio.')
        stream = io.BytesIO()
        sf.write(stream, audio, SAMPLE_RATE, format='WAV', subtype='PCM_24')
        return Preview(stream.getvalue(), dict(settings), fingerprint(settings), details,
                       round(len(audio)/SAMPLE_RATE, 3))

    async def preview_answer(self, source, index, text, *, voice='af_heart', speed=1.0):
        """Running this coroutine generates one answer and displays Play/Save.
"""
        answer = self.find_answer(source, index)
        settings = {'text': text, 'voice': voice, 'speed': float(speed),
                    'audio_processing': 'none', 'preview_version': 2}
        panel = AnswerPlaybackPanel(self, answer, settings)
        previous = self.panels.get((source, index))
        if previous is not None:
            previous.widget.children = panel.widget.children
            panel.widget = previous.widget
        self.panels[(source, index)] = panel
        self.store.update_draft(answer, settings)
        display(panel.widget)
        panel.status.value = 'Generating this answer on CUDA. The first preview loads the model.'
        try:
            loop = asyncio.get_running_loop()
            preview = await loop.run_in_executor(self.executor, partial(self.generate, settings))
            panel.show_preview(preview)
        except Exception as exc:
            panel.status.value = 'Preview failed: ' + escape(str(exc))
            panel.messages.append_stderr(traceback.format_exc())

    def export_portable(self):
        try:
            path = self.store.export_portable()
            self.export_output.outputs = ()
            self.export_output.append_stdout('Save the notebook with Ctrl+S before moving it to another PC.\n')
            self.export_output.append_display_data(FileLink(str(path.relative_to(self.project_root))))
            return path
        except Exception as exc:
            self.export_output.append_stderr(str(exc) + '\n')
            return None

    def answer(self, source, index):
        """Old cell compatibility while an already-open notebook is refreshed.
"""
        key = (source, index)
        if key not in self.panels:
            answer = self.find_answer(source, index)
            settings = self.store.drafts.get(self.store.key(answer),
                {'text':answer.spoken_text,'voice':'af_heart','speed':1.0,'audio_processing':'none','preview_version':2})
            self.panels[key] = AnswerPlaybackPanel(self, answer, settings)
        return self.panels[key].widget
