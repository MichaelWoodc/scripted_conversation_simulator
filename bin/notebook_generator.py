"""Generate raw-text TTS notebooks from labelled QUESTION/ANSWER Word scripts.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path

import nbformat

from answer_tts import ROOT, load_answers


def _existing_cells(path):
    if not path.exists():
        return {}
    notebook = nbformat.read(path, as_version=4)
    return {(c.metadata['answer_source'], c.metadata['answer_index']): c
            for c in notebook.cells if c.cell_type == 'code'
            and 'answer_source' in c.metadata and 'answer_index' in c.metadata}


def _answer_cell(answer, voice, speed):
    literal = '"""' + answer.spoken_text.replace('\\', '\\\\').replace('"', '\\"') + '"""'
    code = (f'# Answer {answer.index:03d}: edit the text, then run this cell.\n'
            f'text = {literal}\n\n'
            f'voice = {voice!r}\n'
            f'speed = {float(speed)!r}\n\n'
            f'await cell_studio.preview_answer({answer.source!r}, {answer.index}, text, voice=voice, speed=speed)')
    cell = nbformat.v4.new_code_cell(code)
    cell.metadata.update(answer_source=answer.source, answer_index=answer.index,
                         source_question=answer.question)
    return cell


def _setup_cell(source_folder):
    return nbformat.v4.new_code_cell(
        'from pathlib import Path\nimport os\nimport sys\nfrom IPython.display import display\n\n'
        'project = next((p for p in (Path.cwd(), *Path.cwd().parents)\n'
        "                if (p / 'bin' / 'cell_answer_review.py').is_file()), None)\n"
        "if project is None:\n    raise RuntimeError('Open this notebook inside the TTS project folder.')\n"
        'os.chdir(project)\n'
        "if str(project / 'bin') not in sys.path:\n    sys.path.insert(0, str(project / 'bin'))\n\n"
        'from answer_tts import load_answers\n'
        'from cell_answer_review import CellAnswerStudio\n'
        f'answers = load_answers(project / {source_folder!r})\n'
        "if 'cell_studio' not in globals() or not isinstance(cell_studio, CellAnswerStudio):\n"
        '    cell_studio = CellAnswerStudio(project_root=project, answers=answers)\n'
        'else:\n    cell_studio.answers = answers\n'
        'display(cell_studio.playback.widget)\n'
        'display(cell_studio.export_widget)\n'
        "print('Ready. Run an answer cell to generate its audio, then Play or Save below it.')"
    )


def _write_notebook(path, answers, source_folder, voice, speed, preserve_edits):
    existing = _existing_cells(path) if preserve_edits else {}
    intro = (
        '# Answer audio from Word scripts\n\n'
        'Run the setup cell once. Edit the raw `text`, `voice`, and `speed` in an answer cell, '
        'then run that cell to generate its audio preview. Click **Play preview**, then '
        '**Save and replace WAV** when happy.\n\n'
        'Save replaces the matching numbered file in '
        '`dist/media/edited/<voice>/speed_1p00/<Word filename>/`. '
        'The exact destination appears under the player. No audio effects are added.\n\n'
        '**Ctrl+S** saves your text inside this notebook. Run only the answer cells you want to generate.'
    )
    cells = [nbformat.v4.new_markdown_cell(intro), _setup_cell(source_folder)]
    last_source = None
    retained = 0
    for answer in answers:
        if answer.source != last_source:
            cells.append(nbformat.v4.new_markdown_cell('## ' + Path(answer.source).stem))
            last_source = answer.source
        old = existing.get((answer.source, answer.index))
        if old is not None:
            cell = deepcopy(old)
            cell.outputs = []
            cell.execution_count = None
            retained += 1
        else:
            cell = _answer_cell(answer, voice, speed)
        cells.append(cell)
    notebook = nbformat.v4.new_notebook(cells=cells, metadata={
        'kernelspec': {'display_name':'Answers TTS (CUDA)', 'language':'python', 'name':'redata-tts'},
        'language_info': {'name':'python', 'version':'3.11'},
        'generator': {'name':'notebook_generator', 'source_folder':source_folder},
    })
    nbformat.validate(notebook)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.partial.ipynb')
    nbformat.write(notebook, temporary)
    temporary.replace(path)
    return {'path': path, 'answers':len(answers), 'preserved_cells':retained}


def generate_notebooks(docx_folder=None, output_folder=None, *, project_root=ROOT,
                       voice='af_heart', speed=1.0, preserve_edits=True):
    """Create one combined notebook and one per DOCX, without generating audio.
"""
    project_root = Path(project_root).resolve()
    docx_folder = Path(docx_folder or project_root/'data'/'scripts').resolve()
    output_folder = Path(output_folder or project_root/'notebooks'/'generated').resolve()
    answers = load_answers(docx_folder)
    try:
        source = docx_folder.relative_to(project_root).as_posix()
    except ValueError:
        source = str(docx_folder)
    groups = OrderedDict()
    for answer in answers:
        groups.setdefault(answer.source, []).append(answer)
    results = [_write_notebook(output_folder/'all_answers.ipynb', answers, source,
                               voice, speed, preserve_edits)]
    for name, records in groups.items():
        results.append(_write_notebook(output_folder/(Path(name).stem+'.ipynb'), records,
                                       source, voice, speed, preserve_edits))
    return results
