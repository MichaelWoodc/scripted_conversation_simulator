"""Resumable Kokoro answer speakers and separate Bella question previews."""
from pathlib import Path
import hashlib
import json
import os
import urllib.request
from urllib.parse import unquote, urlsplit
import wave

from build_site import build, make_catalog, question_audio_path
from project_paths import ROOT, DIST
from response_workbooks import load_responses, workbook_path


class TypedModelSession:
    """Match runtime inputs to the ONNX graph, including float-valued speed."""
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def run(self, output_names, inputs, *args, **kwargs):
        import numpy as np
        dtypes = {'tensor(float)': np.float32, 'tensor(double)': np.float64,
                  'tensor(int64)': np.int64, 'tensor(int32)': np.int32}
        normalized = dict(inputs)
        for field in self.session.get_inputs():
            if field.name in normalized and field.type in dtypes:
                normalized[field.name] = np.asarray(normalized[field.name], dtype=dtypes[field.type])
        return self.session.run(output_names, normalized, *args, **kwargs)


def valid(path):
    try:
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() > 0
    except (OSError, wave.Error, EOFError):
        return False


def download(url, output):
    if output.exists() and output.stat().st_size:
        return
    partial = output.with_suffix(output.suffix + '.partial')
    with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as sink:
        import shutil
        shutil.copyfileobj(response, sink)
    partial.replace(output)


def run(voices=None, question_voice='af_bella', update_heart=False):
    catalog, _ = make_catalog()
    bases = [item for item in catalog['sets'] if item['voice'] == 'af_heart']
    if not bases:
        raise RuntimeError('No complete Heart answer sets found.')
    response_inputs = {item['id']: load_responses(item) for item in bases}
    for item in bases:
        print(f'Reading responses: {workbook_path(item)}', flush=True)
    import soundfile as sf
    from kokoro_onnx import Kokoro
    cache = ROOT / '.cache' / 'kokoro-onnx'
    cache.mkdir(parents=True, exist_ok=True)
    release = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
    download(release + 'kokoro-v1.0.onnx', cache / 'kokoro-v1.0.onnx')
    download(release + 'voices-v1.0.bin', cache / 'voices-v1.0.bin')
    model = Kokoro(str(cache / 'kokoro-v1.0.onnx'), str(cache / 'voices-v1.0.bin'))
    model.sess = TypedModelSession(model.sess)
    available = model.get_voices()
    selected = list(voices or available)
    missing = set(selected + [question_voice]) - set(available)
    if missing:
        raise ValueError(f'Unknown model voices: {sorted(missing)}')
    errors = []

    def synthesize(text, voice, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        samples, rate = model.create(text, voice=voice, speed=1.0,
                                     lang='en-gb' if voice.startswith('b') else 'en-us')
        partial = output.with_suffix('.partial.wav')
        sf.write(str(partial), samples, rate, subtype='PCM_16')
        partial.replace(output)

    # Question previews use Bella, independently of the chosen answer speaker.
    prompts = dict.fromkeys(step['prompt'] for item in bases for step in item['steps'])
    for number, prompt in enumerate(prompts, 1):
        output = DIST / question_audio_path(prompt)
        metadata = output.with_suffix('.json')
        fingerprint = hashlib.sha256((question_voice + prompt).encode()).hexdigest()
        if valid(output) and metadata.exists() and json.loads(metadata.read_text()).get('fingerprint') == fingerprint:
            continue
        synthesize(prompt, question_voice, output)
        metadata.write_text(json.dumps({'voice': question_voice, 'fingerprint': fingerprint}), encoding='utf-8')
        print(f'Question {number}/{len(prompts)}: {question_voice}', flush=True)
    build()

    for voice in selected:
        if voice == 'af_heart' and not update_heart:
            print('Keeping all existing Heart recordings unchanged.', flush=True)
            continue
        for item in bases:
            try:
                for step in item['steps']:
                    for clip in step['clips']:
                        source = DIST / unquote(urlsplit(clip['url']).path)
                        parts = list(source.relative_to(DIST).parts)
                        parts[2] = voice
                        output = DIST.joinpath(*parts)
                        text = response_inputs[item['id']][clip['index']]
                        target_text = output.with_suffix('.txt')
                        if valid(output) and target_text.exists() and target_text.read_text(encoding='utf-8') == text:
                            continue
                        synthesize(text, voice, output)
                        target_text.write_text(text, encoding='utf-8')
                        print(f'{voice}: {item["edition"]} vignette {item["vignette"]}, answer {clip["index"]}', flush=True)
            except Exception as exc:
                errors.append({'voice': voice, 'set': item['id'], 'error': str(exc)})
                print(f'Saved partial work; continuing after {voice}: {exc}', flush=True)
        # Publish only complete sets; interrupted partial sets remain resumable.
        build()
    report = ROOT / 'data' / 'voice_generation_report.json'
    report.write_text(json.dumps({'requested': selected, 'questionVoice': question_voice, 'errors': errors}, indent=2), encoding='utf-8')
    if errors:
        raise RuntimeError(f'{len(errors)} sets need retry; see {report}')
    print('All speakers complete.', flush=True)


if __name__ == '__main__':
    run()
