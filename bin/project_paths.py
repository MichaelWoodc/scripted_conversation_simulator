"""Shared project paths, independent of the process working directory.

Python and build templates live in bin, notebooks in notebooks, editable data
in data, and every published recording lives directly in dist/media.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / 'bin'
DATA = ROOT / 'data'
NOTEBOOKS = ROOT / 'notebooks'
SCRIPTS = DATA / 'scripts'
DIST = ROOT / 'dist'
MEDIA = DIST / 'media'


def audio_root(edition='edited', project_root=ROOT):
    if edition not in ('original', 'edited', 'reviewed'):
        raise ValueError(f'Unknown Audio Files To Use:: {edition}')
    return Path(project_root) / 'dist' / 'media' / edition


def speed_folder(speed):
    return 'speed_' + f'{float(speed):.2f}'.replace('.', 'p')


def answer_directory(source, voice='af_heart', speed=1.0, *, edition='edited', project_root=ROOT):
    return audio_root(edition, project_root) / voice / speed_folder(speed) / Path(source).stem
