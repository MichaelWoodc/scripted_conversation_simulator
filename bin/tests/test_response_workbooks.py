"""Bulk inputs preserve multiline text and reject incomplete response tables."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook
from response_workbooks import ensure_workbook, load_responses


class ResponseWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.item = {'edition': 'edited', 'vignette': 1, 'steps': [
            {'prompt': 'Question?', 'clips': [
                {'index': 1, 'url': 'media/edited/af_heart/session/answer_001.wav?v=1'},
                {'index': 2, 'url': 'media/edited/af_heart/session/answer_002.wav?v=1'}]}]}
        directory = self.root / 'dist/media/edited/af_heart/session'
        directory.mkdir(parents=True)
        (directory / 'answer_001.txt').write_text('First line.\n\nSecond line.\n', encoding='utf-8')
        (directory / 'answer_002.txt').write_text('Another answer.', encoding='utf-8')
        self.path = ensure_workbook(self.item, self.root)

    def edit(self, action):
        book = load_workbook(self.path)
        action(book['Responses'])
        book.save(self.path)
        book.close()

    def test_initial_export_keeps_existing_newlines(self):
        self.assertEqual(load_responses(self.item, self.root)[1], 'First line.\n\nSecond line.\n')

    def test_user_edits_keep_spacing_and_are_not_overwritten(self):
        text = '  Key point.\nNext point.\n\nLast point.  '
        self.edit(lambda sheet: setattr(sheet['C2'], 'value', text))
        ensure_workbook(self.item, self.root)
        self.assertEqual(load_responses(self.item, self.root)[1], text)

    def test_missing_response_is_reported(self):
        self.edit(lambda sheet: sheet.delete_rows(3))
        with self.assertRaisesRegex(ValueError, 'missing answers.*2'):
            load_responses(self.item, self.root)

    def test_duplicate_index_is_reported(self):
        self.edit(lambda sheet: setattr(sheet['A3'], 'value', 1))
        with self.assertRaisesRegex(ValueError, 'duplicate answer_index'):
            load_responses(self.item, self.root)

    def test_empty_response_is_reported(self):
        self.edit(lambda sheet: setattr(sheet['C2'], 'value', '   '))
        with self.assertRaisesRegex(ValueError, 'response must contain plain text'):
            load_responses(self.item, self.root)
