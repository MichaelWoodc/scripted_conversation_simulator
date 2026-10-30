"""Check DOCX extraction, runnable preview cells, and preservation on regeneration.
"""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import nbformat

from answer_tts import ROOT
from notebook_generator import generate_notebooks


class GeneratorTests(unittest.TestCase):
    def test_docx_generates_answer_cells_and_keeps_edits_on_regeneration(self):
        with TemporaryDirectory() as temp:
            output = Path(temp)/'generated'
            results = generate_notebooks(ROOT/'data'/'scripts', output)
            self.assertEqual([r['answers'] for r in results], [109, 38, 28, 43])
            book_path = results[1]['path']
            book = nbformat.read(book_path,as_version=4)
            cell = next(c for c in book.cells if c.metadata.get('answer_index')==3)
            self.assertIn('await cell_studio.preview_answer(',cell.source)
            self.assertNotIn('Textarea',cell.source)
            tree=ast.parse(cell.source)
            original=ast.literal_eval(next(n for n in tree.body if isinstance(n,ast.Assign)).value)
            self.assertIn('quarterly',original)
            cell.source=cell.source.replace(original,'My manually edited text.')
            nbformat.write(book,book_path)
            again=generate_notebooks(ROOT/'data'/'scripts',output)
            self.assertEqual(again[1]['preserved_cells'],38)
            regenerated=nbformat.read(book_path,as_version=4)
            edited=next(c for c in regenerated.cells if c.metadata.get('answer_index')==3)
            self.assertIn('My manually edited text.',edited.source)
            generate_notebooks(ROOT/'data'/'scripts',output,preserve_edits=False)
            reset=nbformat.read(book_path,as_version=4)
            self.assertIn(original,next(c.source for c in reset.cells if c.metadata.get('answer_index')==3))
            self.assertFalse(list(output.rglob('*.wav')))


if __name__=='__main__':
    unittest.main()
