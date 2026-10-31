"""Execute the speaker-generation notebook in the background with checkpoints."""
import os
from pathlib import Path
import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'notebooks' / 'generate_all_answer_voices.ipynb'
os.chdir(ROOT)
os.environ.setdefault('OMP_NUM_THREADS', '2')
print(f'Executing {path}', flush=True)
book = nbformat.read(path, as_version=4)


def checkpoint(**kwargs):
    nbformat.write(book, path)


client = NotebookClient(book, timeout=None, kernel_name='python3',
                        resources={'metadata': {'path': str(ROOT)}},
                        on_cell_executed=checkpoint)
try:
    client.execute()
finally:
    checkpoint()
