"""Editable, multiline response inputs for the bulk voice generator."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

from project_paths import ROOT


def workbook_path(item, project=ROOT):
    return Path(project) / 'data' / 'responses' / f"{item['edition']}-vignette-{item['vignette']}.xlsx"


def expected_responses(item):
    return {clip['index']: step['prompt'] for step in item['steps'] for clip in step['clips']}


def ensure_workbook(item, project=ROOT):
    """Seed from the current Heart transcripts once; never replace user edits."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    path = workbook_path(item, project)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.title = 'Responses'
    sheet.append(['answer_index', 'question', 'response'])
    entries = {}
    for step in item['steps']:
        for clip in step['clips']:
            transcript = Path(project) / 'dist' / unquote(urlsplit(clip['url']).path)
            transcript = transcript.with_suffix('.txt')
            if not transcript.exists():
                raise FileNotFoundError(f'Cannot seed response input: {transcript}')
            entries[clip['index']] = (step['prompt'], transcript.read_text(encoding='utf-8'))
    for index, (question, response) in sorted(entries.items()):
        sheet.append([index, question, response])
        sheet.cell(sheet.max_row, 3).data_type = 's'
        sheet.row_dimensions[sheet.max_row].height = 60
    sheet.freeze_panes = 'C2'
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in [('A', 16), ('B', 65), ('C', 95)]:
        sheet.column_dimensions[column].width = width
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='173B32')
    help_sheet = book.create_sheet('Instructions')
    for line in [
        'Edit the response column on the Responses sheet, then save this workbook.',
        'Use Alt+Enter inside an Excel cell to add a newline. Existing newlines are preserved.',
        'Text is passed directly to the speech model. No extra silence or pause processing is added.',
        'Keep answer_index values unchanged. The question column is context only.',
        'Rerun the generator notebook to use your saved changes. Unchanged audio is reused.',
        'Heart recordings remain protected by default. Set UPDATE_HEART = True in the notebook to regenerate Heart too.',
    ]:
        help_sheet.append([line])
    help_sheet.column_dimensions['A'].width = 120
    for row in help_sheet:
        row[0].alignment = Alignment(wrap_text=True)
        help_sheet.row_dimensions[row[0].row].height = 32
    book.save(path)
    book.close()
    return path


def load_responses(item, project=ROOT):
    from openpyxl import load_workbook
    path = ensure_workbook(item, project)
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = book['Responses']
        headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        for name in ['answer_index', 'response']:
            if headers.count(name) != 1:
                raise ValueError(f'{path}: expected exactly one {name} column')
        index_column, text_column = headers.index('answer_index'), headers.index('response')
        result = {}
        for row_number, row in enumerate(sheet.iter_rows(min_row=2), 2):
            if all(cell.value is None for cell in row):
                continue
            index, cell = row[index_column].value, row[text_column]
            if type(index) is not int or index in result:
                raise ValueError(f'{path}, row {row_number}: invalid or duplicate answer_index {index!r}')
            if cell.data_type == 'f' or not isinstance(cell.value, str) or not cell.value.strip():
                raise ValueError(f'{path}, row {row_number}: response must contain plain text')
            result[index] = cell.value  # Preserve newlines and spacing exactly.
        expected = set(expected_responses(item))
        if set(result) != expected:
            raise ValueError(f'{path}: missing answers {sorted(expected-set(result))}; unexpected answers {sorted(set(result)-expected)}')
        return result
    finally:
        book.close()


if __name__ == '__main__':
    from build_site import make_catalog
    catalog, _ = make_catalog()
    for item in catalog['sets']:
        if item['voice'] == 'af_heart':
            print(ensure_workbook(item))
