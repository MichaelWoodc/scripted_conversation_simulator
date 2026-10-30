"""Extract labelled Word-script answers and render them with local CUDA TTS.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from project_paths import ROOT, SCRIPTS, audio_root, speed_folder
os.environ.setdefault('HF_HOME', str(ROOT / '.cache' / 'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
SAMPLE_RATE = 24000
MODEL_ID = 'hexgrad/Kokoro-82M'
RENDER_VERSION = 2
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
# No leading boundary: the supplied files contain e.g. "hereQUESTION".
LABEL = re.compile(r'(QUESTION|ANSWER)\b(?:[ \t]*\(([^)\n]+)\))?[ \t]*:?[ \t]*')
CUE = re.compile(r'\(\s*(long pause|pause|tentatively|firmly|annoyed)\s*\)', re.I)

VOICES = [
    ('Heart - female, American (recommended)', 'af_heart'),
    ('Bella - female, American', 'af_bella'),
    ('Nicole - female, American, soft', 'af_nicole'),
    ('Sarah - female, American', 'af_sarah'),
    ('Aoede - female, American', 'af_aoede'),
    ('Kore - female, American', 'af_kore'),
    ('Nova - female, American', 'af_nova'),
    ('Alloy - female, American', 'af_alloy'),
    ('Jessica - female, American', 'af_jessica'),
    ('River - female, American', 'af_river'),
    ('Sky - female, American', 'af_sky'),
    ('Emma - female, British', 'bf_emma'),
    ('Isabella - female, British', 'bf_isabella'),
    ('Alice - female, British', 'bf_alice'),
    ('Lily - female, British', 'bf_lily'),
    ('Michael - male, American', 'am_michael'),
    ('Fenrir - male, American', 'am_fenrir'),
    ('Puck - male, American', 'am_puck'),
    ('Adam - male, American', 'am_adam'),
    ('Echo - male, American', 'am_echo'),
    ('Eric - male, American', 'am_eric'),
    ('Liam - male, American', 'am_liam'),
    ('Onyx - male, American', 'am_onyx'),
    ('Santa - male, American', 'am_santa'),
    ('George - male, British', 'bm_george'),
    ('Daniel - male, British', 'bm_daniel'),
    ('Fable - male, British', 'bm_fable'),
    ('Lewis - male, British', 'bm_lewis'),
]


@dataclass
class Answer:
    source: str
    index: int
    question: str
    raw_answer: str
    spoken_text: str
    cues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def clean_text(text: str) -> tuple[str, list[str]]:
    """Repair punctuation for speech without rewriting the speaker's words.
"""
    notes = []
    if '\ufffd' in text:
        notes.append('Source contains replacement characters; apostrophes/pauses inferred. Review raw_answer.')
        text = re.sub(r"(?<=[A-Za-z])\ufffd(?=(?:s|t|re|ve|ll|d|m)\b)", "'", text)
        text = re.sub(r'\ufffd+', '... ', text)
    text = text.translate(str.maketrans({'\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"', '\u2014': ', ', '\u2013': ', ', '\u00a0': ' ', '\u2026': '...'}))
    text = re.sub(r'(?<=[.!?])(?=[A-Z])', ' ', text)
    text = re.sub(r'\.{2,}', '...', text)
    text = re.sub(r'\.\.\.(?=[A-Za-z])', '... ', text)
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text, notes


def read_docx(path: Path) -> str:
    with ZipFile(path) as archive:
        body = ET.fromstring(archive.read('word/document.xml')).find('w:body', NS)
    if body is None:
        raise ValueError(f'No document body: {path.name}')
    # Includes paragraphs inside tables, in document order; joins split Word runs.
    return '\n'.join(''.join(
        node.text or '' for node in p.findall('.//w:t', NS)
    ) for p in body.iterfind('.//w:p', NS))


def parse_script(text: str, source: str) -> list[Answer]:
    markers = list(LABEL.finditer(text))
    if not markers:
        raise ValueError(f'{source}: no QUESTION/ANSWER labels found; refusing to narrate the whole file.')
    records = []
    question = ''
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        content = text[marker.end():end].strip()
        if marker[1] == 'QUESTION':
            question = content
            continue
        if not content:
            raise ValueError(f'{source}: empty ANSWER near character {marker.start()}')
        cues = ([marker[2]] if marker[2] else []) + CUE.findall(content)
        spoken, notes = clean_text(CUE.sub(' ', content))
        if not spoken:
            raise ValueError(f'{source}: answer has no spoken words.')
        if not question:
            notes.append('Answer has no preceding question.')
        records.append(Answer(source, len(records) + 1, question, content, spoken, cues, notes))
    return records


def load_answers(folder: Path | str = SCRIPTS) -> list[Answer]:
    folder = Path(folder)
    legacy = list(folder.glob('*.doc'))
    if legacy:
        raise ValueError('Convert these legacy .doc files to .docx first: ' + ', '.join(p.name for p in legacy))
    paths = sorted(p for p in folder.glob('*.docx') if not p.name.startswith('~$'))
    if not paths:
        raise FileNotFoundError(f'No .docx files found in {folder}')
    return [answer for path in paths for answer in parse_script(read_docx(path), path.name)]


def slug(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]+', '_', text).strip('_')


def export_answers(answers: list[Answer], folder: Path | str) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'extracted_answers.json').write_text(
        json.dumps([asdict(a) for a in answers], ensure_ascii=False, indent=2), encoding='utf-8')
    with (folder / 'extracted_answers.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Answer.__dataclass_fields__))
        writer.writeheader()
        for answer in answers:
            row = asdict(answer)
            row['cues'] = '; '.join(row['cues'])
            row['notes'] = '; '.join(row['notes'])
            writer.writerow(row)
    for source in dict.fromkeys(a.source for a in answers):
        lines = [f'{a.index:03d}. {a.spoken_text}' for a in answers if a.source == source]
        (folder / f'{slug(Path(source).stem)}_answers.txt').write_text('\n\n'.join(lines), encoding='utf-8')


class TTSEngine:
    """A shared model with separate American/British pronunciation pipelines.
"""
    render_settings = {'audio_processing': 'none'}
    def __init__(self, device: str = 'cuda'):
        import torch
        from kokoro import KModel
        if device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable. Choose the Answers TTS (CUDA) kernel and rerun setup_tts.ps1.')
        self.device = device
        # FP32 is deliberate: reliable on the T1000 and ample room for this model.
        self.model = KModel(repo_id=MODEL_ID).to(device).eval()
        self.pipelines = {}

    def pipeline(self, voice: str):
        from kokoro import KPipeline
        if voice not in dict((v, label) for label, v in VOICES):
            raise ValueError(f'Unknown voice: {voice}')
        language = voice[0]
        if language not in self.pipelines:
            self.pipelines[language] = KPipeline(lang_code=language, repo_id=MODEL_ID, model=self.model)
        pipeline = self.pipelines[language]
        if pipeline.g2p.fallback is None:
            raise RuntimeError('English pronunciation fallback unavailable. Rerun setup_tts.ps1.')
        return pipeline

    def synthesize(self, text: str, voice: str = 'af_heart', speed: float = 1.0, *, long_pause: bool = False):
        import numpy as np
        import torch
        if not 0.7 <= speed <= 1.3:
            raise ValueError('Speed must be between 0.7 and 1.3.')
        if not text.strip():
            raise ValueError('No text to synthesize.')
        chunks = []
        with torch.inference_mode():
            for result in self.pipeline(voice)(text, voice=voice, speed=speed):
                if result.audio is None:
                    raise RuntimeError('The model did not return audio.')
                audio = result.audio.detach().cpu().numpy().reshape(-1).astype(np.float32)
                if audio.size == 0 or not np.isfinite(audio).all():
                    raise RuntimeError('Model returned empty or nonfinite audio.')
                audio = self.adapt_chunk(result, audio)
                chunks.append(audio)
        if not chunks:
            raise RuntimeError(f'No pronounceable audio for {text!r}')
        return self.finish_audio(np.concatenate(chunks))

    def finish_audio(self, audio, *, long_pause=False):
        import numpy as np
        # Model samples pass through untouched: no stretching, fades, padding,
        # amplitude normalization, or filters. long_pause is compatibility only.
        if audio.size == 0 or not np.isfinite(audio).all():
            raise RuntimeError('The model returned invalid audio.')
        return audio

    def adapt_chunk(self, result, audio):
        return audio


def render_batch(answers: list[Answer], engine: TTSEngine, output: Path | str = audio_root('original'),
                 voice: str = 'af_heart', speed: float = 1.0, gap: float = 0.65,
                 resume: bool = True, progress: Callable | None = None) -> list[dict]:
    """Individual WAVs, combined answer tracks, transcripts, and traceable manifest.
"""
    import numpy as np
    import soundfile as sf
    if not answers:
        raise ValueError('Select at least one answer.')
    if not 0 <= gap <= 3:
        raise ValueError('Gap must be between 0 and 3 seconds.')
    output = Path(output)
    export_answers(answers, output / 'transcripts')
    variant = output / voice / speed_folder(speed)
    variant.mkdir(parents=True, exist_ok=True)
    records = []
    for done, answer in enumerate(answers, 1):
        doc_folder = variant / Path(answer.source).stem
        doc_folder.mkdir(parents=True, exist_ok=True)
        wav_path = doc_folder / f'answer_{answer.index:03d}.wav'
        metadata_path = wav_path.with_suffix('.json')
        settings = {'model': MODEL_ID, 'voice': voice, 'speed': speed,
                    'render_version': RENDER_VERSION, 'answer': asdict(answer)}
        settings.update(getattr(engine, 'render_settings', {}))
        fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = None
        if resume and wav_path.exists() and metadata_path.exists():
            cached = json.loads(metadata_path.read_text(encoding='utf-8'))
            if cached.get('fingerprint') != fingerprint:
                cached = None
            else:
                info = sf.info(wav_path)
                if info.frames == 0 or info.samplerate != SAMPLE_RATE:
                    cached = None
        if cached:
            record = cached
        else:
            audio = engine.synthesize(answer.spoken_text, voice, speed,
                                      long_pause=any(c.lower() == 'long pause' for c in answer.cues))
            # Write complete audio atomically, so interrupted runs can safely resume.
            temp = wav_path.with_suffix('.partial.wav')
            sf.write(str(temp), audio, SAMPLE_RATE, subtype='PCM_24')
            temp.replace(wav_path)
            record = {**settings, 'fingerprint': fingerprint, 'audio_file': str(wav_path.relative_to(output)),
                      'duration_seconds': round(len(audio) / SAMPLE_RATE, 3),
                      'sample_rate': SAMPLE_RATE, 'subtype': 'PCM_24',
                      'created_utc': datetime.now(timezone.utc).isoformat()}
            if hasattr(engine, 'last_timing'):
                record['hesitation_timing'] = engine.last_timing
            metadata_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        wav_path.with_suffix('.txt').write_text(answer.spoken_text, encoding='utf-8')
        records.append(record)
        if progress:
            progress(done, len(answers), answer, wav_path, bool(cached))
    # Assemble by streaming to disk rather than holding all answers in RAM.
    for source in dict.fromkeys(a.source for a in answers):
        doc_folder = variant / Path(source).stem
        selected = [a for a in answers if a.source == source]
        # A subset render must not replace a previously completed document track.
        full_count = len(parse_script(read_docx(SCRIPTS / source), source))
        name = 'all_answers.wav' if len(selected) == full_count else 'selected_answers.wav'
        combined = doc_folder / name
        temp = combined.with_suffix('.partial.wav')
        timeline = []
        frames = 0
        with sf.SoundFile(str(temp), mode='w', samplerate=SAMPLE_RATE, channels=1, subtype='PCM_24') as sink:
            for i, answer in enumerate(selected):
                if i:
                    silence = np.zeros(round(gap * SAMPLE_RATE), dtype=np.float32)
                    sink.write(silence)
                    frames += len(silence)
                start = frames / SAMPLE_RATE
                audio, _ = sf.read(str(doc_folder / f'answer_{answer.index:03d}.wav'), dtype='float32')
                sink.write(audio)
                frames += len(audio)
                timeline.append({'answer_index': answer.index, 'start_seconds': round(start, 3),
                                 'end_seconds': round(frames / SAMPLE_RATE, 3), 'text': answer.spoken_text})
        temp.replace(combined)
        combined.with_suffix('.json').write_text(json.dumps({'source': source, 'voice': voice, 'speed': speed,
            'gap_seconds': gap, 'answers': timeline}, ensure_ascii=False, indent=2), encoding='utf-8')
    # Merge manifest entries so rendering a subset does not discard previous results.
    manifest_path = variant / 'manifest.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
    merged = {(r['answer']['source'], r['answer']['index']): r for r in previous}
    merged.update({(r['answer']['source'], r['answer']['index']): r for r in records})
    manifest_path.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-only', action='store_true')
    parser.add_argument('--warmup', action='store_true')
    parser.add_argument('--voice', default='af_heart', choices=[v for _, v in VOICES])
    parser.add_argument('--speed', default=1.0, type=float)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--emphasized-punctuation', action='store_true',
                        help='Punctuation presets only; direct model audio without effects.')
    args = parser.parse_args()
    if args.output is None:
        args.output = audio_root('edited' if args.emphasized_punctuation else 'original')
    answers = load_answers()
    if args.emphasized_punctuation:
        from emphasized_delivery import emphasize_answers
        answers = emphasize_answers(answers)
    export_answers(answers, args.output / 'transcripts')
    for source in dict.fromkeys(a.source for a in answers):
        print(f'{source}: {sum(a.source == source for a in answers)} answers', flush=True)
    if args.extract_only:
        return
    import torch
    print(f'PyTorch {torch.__version__}; CUDA {torch.version.cuda}; GPU {torch.cuda.get_device_name(0)}', flush=True)
    if args.emphasized_punctuation:
        from emphasized_delivery import EmphasizedTTSEngine
        engine = EmphasizedTTSEngine()
        print('Delivery: punctuation presets only; direct model audio without effects.', flush=True)
    else:
        engine = TTSEngine()
    if args.warmup:
        import soundfile as sf
        audio = engine.synthesize('Yes. The employee received the training about three months ago.', args.voice, args.speed)
        sf.write(str(args.output / 'voice_preview.wav'), audio, SAMPLE_RATE, subtype='PCM_24')
        print('Model and default female voice ready.', flush=True)
        return
    def progress(done, total, answer, path, cached):
        print(f'[{done}/{total}] {"Reused" if cached else "Saved"} {path.relative_to(ROOT)}', flush=True)
    records = render_batch(answers[:args.limit] if args.limit else answers, engine, args.output,
                           args.voice, args.speed, progress=progress)
    print(f'Finished: {len(records)} answers; {sum(r["duration_seconds"] for r in records):.1f} seconds of audio.', flush=True)
    return records


if __name__ == '__main__':
    main()
