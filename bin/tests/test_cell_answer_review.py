"""Verify raw-cell previews replace only the requested numbered output on Save.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ipywidgets as W
import numpy as np

from answer_tts import load_answers
from cell_answer_review import CellAnswerStudio


class FakeEngine:
    def __init__(self):
        self.texts = []

    def synthesize(self, text, voice, speed):
        self.texts.append(text)
        return np.array([0., .1, -.2, .3, 0.], dtype=np.float32)


class CellReviewTests(unittest.TestCase):
    def test_save_replaces_requested_file_with_exact_preview(self):
        with TemporaryDirectory() as temp:
            engine = FakeEngine()
            studio = CellAnswerStudio(project_root=temp, answers=load_answers(), engine_factory=lambda _: engine)
            answer = next(a for a in studio.answers if 'Vignette 1' in a.source and a.index == 3)
            text = 'Um.\nthey receive the training I would sayy, quarterly.\nso every 3 months we retrain,\ngo through behavior plans,\nand retrain.'
            target = (Path(temp)/'dist'/'media'/'edited'/'af_heart'/'speed_1p00'/
                      Path(answer.source).stem/'answer_003.wav')
            target.parent.mkdir(parents=True)
            target.write_bytes(b'previous approved audio')
            with patch('cell_answer_review.display'):
                asyncio.run(studio.preview_answer(answer.source, 3, text))
            panel = studio.panels[(answer.source, 3)]
            self.assertEqual(panel.target, target)
            self.assertEqual(target.read_bytes(), b'previous approved audio')
            self.assertFalse(panel.play_button.disabled)
            self.assertFalse(panel.save_button.disabled)
            self.assertEqual(engine.texts, [text])
            self.assertEqual(panel.save(), target)
            self.assertEqual(target.read_bytes(), panel.preview.wav_bytes)
            self.assertEqual(target.with_suffix('.txt').read_text(encoding='utf-8'), text)
            self.assertEqual(json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))['rendered_text'], text)
            self.assertEqual(engine.texts, [text])
            self.assertFalse(any(isinstance(w, W.Textarea) for w in panel.widget.children))
            studio.executor.shutdown()

    def test_other_cell_does_not_change_save_snapshot_and_rerun_rejects_old_save(self):
        with TemporaryDirectory() as temp:
            studio = CellAnswerStudio(project_root=temp, answers=load_answers(), engine_factory=lambda _: FakeEngine())
            source = studio.answers[0].source
            with patch('cell_answer_review.display'):
                asyncio.run(studio.preview_answer(source, 3, 'First text.'))
                first = studio.panels[(source, 3)]
                asyncio.run(studio.preview_answer(source, 9, 'Other cell text.'))
                self.assertEqual(first.save().with_suffix('.txt').read_text(encoding='utf-8'), 'First text.')
                old_root = first.widget
                asyncio.run(studio.preview_answer(source, 3, 'Updated text.'))
            self.assertIs(studio.panels[(source, 3)].widget, old_root)
            self.assertIsNone(first.save())
            self.assertEqual(studio.panels[(source, 3)].save().with_suffix('.txt').read_text(encoding='utf-8'), 'Updated text.')
            studio.executor.shutdown()


if __name__ == '__main__':
    unittest.main()
