"""Jupyter controls for previewing voices and generating answer-only tracks.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from html import escape
from pathlib import Path
import traceback

import ipywidgets as W
from IPython.display import Audio, FileLink, HTML, clear_output, display
from project_paths import audio_root

from answer_tts import ROOT, SAMPLE_RATE, VOICES, clean_text, render_batch


def build_widget(answers, engine_loader):
    sources = list(dict.fromkeys(a.source for a in answers))
    documents = W.SelectMultiple(options=[(f'{i + 1}. {s}', s) for i, s in enumerate(sources)],
                                 value=tuple(sources), description='Documents:', rows=min(6, len(sources)),
                                 layout=W.Layout(width='100%'))
    voice = W.Dropdown(options=VOICES, value='af_heart', description='Voice:', layout=W.Layout(width='95%'))
    delivery = W.Dropdown(options=[('Original script punctuation', 'original'),
                                   ('Punctuation presets only (no effects)', 'emphasized')],
                          value='emphasized', description='Delivery:', layout=W.Layout(width='95%'))
    speed = W.FloatSlider(value=1, min=0.75, max=1.25, step=0.05, description='Speed:', readout_format='.2f',
                          continuous_update=False, layout=W.Layout(width='85%'))
    gap = W.FloatSlider(value=0.65, min=0, max=2, step=0.05, description='Answer gap:', readout_format='.2f',
                        continuous_update=False, layout=W.Layout(width='85%'))
    resume = W.Checkbox(value=True, description='Reuse completed audio with matching settings', indent=False)
    sample = W.Dropdown(description='Answer:', layout=W.Layout(width='95%'))
    context = W.HTML()
    text = W.Textarea(description='Read aloud:', layout=W.Layout(width='95%', height='110px'))
    preview = W.Button(description='Preview voice', icon='play', button_style='info')
    single = W.Button(description='Save this answer', icon='save')
    batch = W.Button(description='Generate selected documents', icon='volume-up', button_style='success',
                      layout=W.Layout(width='265px'))
    progress = W.IntProgress(value=0, min=0, max=1, description='Progress:', layout=W.Layout(width='95%'))
    status = W.HTML('Choose a voice and preview it, then generate the selected documents.')
    output = W.Output()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='answer-tts')
    controls = [documents, voice, delivery, speed, gap, resume, sample, text, preview, single, batch]
    tasks = set()
    from emphasized_delivery import emphasize_answers
    emphasized = emphasize_answers(answers)

    def current_answers():
        return emphasized if delivery.value == 'emphasized' else answers

    def update_sample(_=None):
        if sample.value is None:
            text.value = ''
            context.value = ''
            return
        answer = current_answers()[sample.value]
        text.value = answer.spoken_text
        details = f'<b>Question (context):</b> {escape(answer.question)}'
        if answer.cues:
            details += f'<br><b>Delivery cues:</b> {escape(", ".join(answer.cues))}'
        if answer.notes:
            details += f'<br><b>Text review:</b> {escape(" ".join(answer.notes))}'
        context.value = details

    def update_documents(_=None):
        indices = [i for i, a in enumerate(answers) if a.source in documents.value]
        sample.options = [(f'Vignette {sources.index(answers[i].source) + 1} / {answers[i].index:03d}: '
                           f'{answers[i].spoken_text[:85]}', i) for i in indices]
        if indices:
            sample.value = next((i for i in indices if len(answers[i].spoken_text) > 90), indices[0])
        update_sample()

    sample.observe(update_sample, names='value')
    documents.observe(update_documents, names='value')
    delivery.observe(update_sample, names='value')
    update_documents()

    def set_busy(busy):
        for control in controls:
            control.disabled = busy
        progress.bar_style = 'info' if busy else ''

    async def run(action):
        if action != 'preview' and not documents.value:
            status.value = 'Select at least one document.'
            return
        if action in ('preview', 'single') and (sample.value is None or not text.value.strip()):
            status.value = 'Select an answer with some text.'
            return
        set_busy(True)
        progress.value = 0
        progress.max = 1
        selected_voice, selected_speed, selected_gap = voice.value, speed.value, gap.value
        selected_style = delivery.value
        output_folder = audio_root('edited' if selected_style == 'emphasized' else 'original')
        selected = [a for a in current_answers() if a.source in documents.value]
        if action == 'single':
            spoken, notes = clean_text(text.value)
            selected = [replace(current_answers()[sample.value], spoken_text=spoken,
                                notes=current_answers()[sample.value].notes + notes)]
        with output:
            clear_output(wait=True)
        try:
            loop = asyncio.get_running_loop()
            status.value = 'Loading the voice model on CUDA. The first run downloads model files.'
            engine = await loop.run_in_executor(executor, partial(engine_loader, selected_style))
            if action == 'preview':
                status.value = 'Generating voice preview...'
                audio = await loop.run_in_executor(executor, partial(engine.synthesize, text.value,
                                                                      selected_voice, selected_speed))
                with output:
                    display(Audio(audio, rate=SAMPLE_RATE, normalize=False))
                progress.value = 1
                status.value = f'Preview ready: {escape(selected_voice)}, speed {selected_speed:.2f}.'
            else:
                progress.max = len(selected)
                def report(done, total, answer, path, cached):
                    def update():
                        progress.value = done
                        status.value = (f'{done}/{total} answers {"ready" if cached else "generated"} '
                                        f'&mdash; {escape(answer.source)}, answer {answer.index:03d}')
                    loop.call_soon_threadsafe(update)
                records = await loop.run_in_executor(executor, partial(
                    render_batch, selected, engine, output_folder, selected_voice,
                    selected_speed, selected_gap, resume.value, report))
                relative_output = output_folder.relative_to(ROOT)
                variant = relative_output / selected_voice / ('speed_' + f'{selected_speed:.2f}'.replace('.', 'p'))
                with output:
                    display(HTML(f'<b>Saved {len(records)} answer files.</b>'))
                    if action == 'single':
                        wav = relative_output / records[0]['audio_file']
                        display(Audio(filename=str(wav), normalize=False))
                        display(FileLink(str(wav)))
                    else:
                        for source in documents.value:
                            path = variant / Path(source).stem / 'all_answers.wav'
                            display(HTML(f'<b>{escape(Path(source).stem)}</b>'))
                            display(Audio(filename=str(path), normalize=False))
                            display(FileLink(str(path)))
                    display(FileLink(str(variant / 'manifest.json')))
                status.value = f'Complete. Files saved in {escape(str(variant))}.'
            progress.bar_style = 'success'
        except Exception as exc:
            progress.bar_style = 'danger'
            status.value = f'Generation stopped: {escape(str(exc))}. Completed files can be reused.'
            with output:
                traceback.print_exc()
        finally:
            for control in controls:
                control.disabled = False

    def launch(action):
        task = asyncio.create_task(run(action))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    preview.on_click(lambda _: launch('preview'))
    single.on_click(lambda _: launch('single'))
    batch.on_click(lambda _: launch('batch'))
    return W.VBox([
        W.HTML('<h3>Answer audio studio</h3><p>Heart is the starting female voice. '
               'Preview several voices to choose the delivery you prefer.</p>'),
        documents, voice, delivery, speed, gap, resume, W.HTML('<hr>'), sample, context, text,
        W.HTML('<small>Text edits apply to Preview and Save this answer. '
               'Generate selected documents uses the extracted script text. '
               'Delivery cues are shown for review; no audio effects are applied.</small>'),
        W.HBox([preview, single]), batch, progress, status, output,
    ], layout=W.Layout(max_width='1050px'))
