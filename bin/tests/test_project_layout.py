"""Exercise batch output, notebook Save, and static hosting together."""
import asyncio
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import nbformat
import numpy as np

from answer_tts import load_answers, render_batch
from build_site import build
from cell_answer_review import CellAnswerStudio
from notebook_generator import generate_notebooks
from project_paths import DATA, ROOT, answer_directory, audio_root


class FakeEngine:
    def synthesize(self, text, voice, speed, **kwargs):
        return np.array([0., .2, -.2, .1, 0.], dtype=np.float32)


class LayoutTests(unittest.TestCase):
    def test_batch_and_notebook_save_use_the_same_static_media(self):
        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            shutil.copytree(DATA / 'scripts', project / 'data' / 'scripts')
            shutil.copy2(DATA / 'question_overrides.json', project / 'data' / 'question_overrides.json')
            answers = load_answers(project / 'data' / 'scripts')[:38]
            engine = FakeEngine()
            render_batch(answers, engine, output=audio_root('edited', project))
            catalog, media = build(static_audio=True, project=project)
            self.assertEqual(len(catalog['sets']), 1)
            item = catalog['sets'][0]
            clip = item['steps'][0]['clips'][0]
            wav = project / 'dist' / unquote(urlsplit(clip['url']).path)
            self.assertEqual(wav, answer_directory(answers[0].source, project_root=project) / 'answer_001.wav')
            self.assertEqual(media[unquote(urlsplit(clip['url']).path)], wav)
            studio = CellAnswerStudio(project_root=project, answers=answers, engine_factory=lambda _: engine)
            self.addCleanup(studio.executor.shutdown)
            with patch('cell_answer_review.display'):
                asyncio.run(studio.preview_answer(answers[0].source, 1, 'Edited in the notebook.'))
            panel = studio.panels[(answers[0].source, 1)]
            self.assertEqual(panel.save(), wav)
            self.assertEqual(wav.read_bytes(), panel.preview.wav_bytes)
            build(static_audio=True, project=project)
            self.assertEqual(wav.read_bytes(), panel.preview.wav_bytes)
            saved_catalog = json.loads((project / 'dist' / 'catalog.json').read_text(encoding='utf-8'))
            for recording in saved_catalog['sets']:
                for step in recording['steps']:
                    for clip in step['clips']:
                        self.assertTrue((project / 'dist' / unquote(urlsplit(clip['url']).path)).is_file())

    def test_new_notebooks_default_to_the_notebooks_folder(self):
        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            shutil.copytree(DATA / 'scripts', project / 'data' / 'scripts')
            results = generate_notebooks(project_root=project)
            self.assertTrue(all(item['path'].parent == project / 'notebooks' / 'generated' for item in results))
            book = nbformat.read(results[0]['path'], as_version=4)
            setup = book.cells[1].source
            self.assertIn("p / 'bin' / 'cell_answer_review.py'", setup)
            self.assertIn("sys.path.insert(0, str(project / 'bin'))", setup)
            self.assertIn("load_answers(project / 'data/scripts')", setup)
            self.assertFalse(list(project.rglob('*.wav')))

    def test_saved_notebooks_find_bin_from_their_new_locations(self):
        for path in (ROOT / 'notebooks').rglob('*.ipynb'):
            book = nbformat.read(path, as_version=4)
            setup = next(cell.source for cell in book.cells
                         if cell.cell_type == 'code' and 'project = next(' in cell.source)
            self.assertIn("str(project / 'bin')", setup, str(path))
            self.assertNotIn('audio_output_emphasized_punctuation', setup, str(path))
