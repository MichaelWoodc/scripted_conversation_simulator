# Bulk response inputs

Each session has an Excel workbook:

- `edited-vignette-1.xlsx`, `edited-vignette-2.xlsx`, `edited-vignette-3.xlsx`
- `original-vignette-1.xlsx`, `original-vignette-2.xlsx`, `original-vignette-3.xlsx`

Open the **Responses** sheet and edit the **response** column. Use **Alt+Enter**
inside a cell for newlines. Keep **answer_index** unchanged; **question** is only
there for context. Save and close the workbook before rerunning
`notebooks/generate_all_answer_voices.ipynb`.

The generator reads the response text directly, preserving newlines and spacing.
It adds no silence and performs no extra pause processing. Existing workbooks are
never replaced automatically. Each run reads a snapshot of the saved workbooks;
edits made during a running job take effect on the next run. Missing, duplicate,
or blank responses produce an error naming the workbook and row.

Unchanged recordings are reused. Heart recordings remain protected by default;
set **UPDATE_HEART = True** in the notebook to apply your edits to Heart as well.
