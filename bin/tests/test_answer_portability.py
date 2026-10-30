"""Verify text edits survive copying the export to another PC/project folder.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from answer_review import AnswerReviewStudio


class PortabilityTests(unittest.TestCase):
    def test_autosaved_text_and_voice_restore_from_portable_export(self):
        with TemporaryDirectory() as temp:
            first_pc = Path(temp) / 'first_pc'
            second_pc = Path(temp) / 'second_pc'
            first_pc.mkdir()
            (first_pc / 'notebooks').mkdir()
            (first_pc / 'bin').mkdir()
            (first_pc / 'notebooks' / 'answer_review.ipynb').write_text('{"cells": []}', encoding='utf-8')
            (first_pc / 'bin' / 'answer_review.py').write_text('# support code', encoding='utf-8')
            studio = AnswerReviewStudio(output=first_pc/'dist'/'media'/'reviewed', project_root=first_pc)
            answer = next(a for a in studio.answers if 'Vignette 1' in a.source and a.index == 9)
            studio.answer(answer.source, answer.index)
            editor = studio.editors[(answer.source, answer.index)]
            text = 'Uh... i would sayy, both.'
            editor.text.value = text
            editor.voice.value = 'af_bella'
            saved = json.loads((first_pc/'data'/'answer_edits.json').read_text(encoding='utf-8'))
            self.assertEqual(saved[studio.store.key(answer)]['text'], text)
            exported = studio.export_portable()
            with ZipFile(exported) as archive:
                self.assertIn('data/answer_edits.json', archive.namelist())
                self.assertIn('notebooks/answer_review.ipynb', archive.namelist())
                self.assertIn('bin/answer_review.py', archive.namelist())
                self.assertFalse(any(name.startswith('dist/') for name in archive.namelist()))
                archive.extractall(second_pc)
            other = AnswerReviewStudio(output=second_pc/'dist'/'media'/'reviewed', project_root=second_pc)
            other.answer(answer.source, answer.index)
            restored = other.editors[(answer.source, answer.index)]
            self.assertEqual(restored.text.value, text)
            self.assertEqual(restored.voice.value, 'af_bella')
            self.assertFalse(other.store.drafts_path.exists())
            self.assertIsNone(restored._preview)
            studio.executor.shutdown()
            other.executor.shutdown()


if __name__ == '__main__':
    unittest.main()
