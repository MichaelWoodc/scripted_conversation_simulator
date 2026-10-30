"""Optional editable punctuation presets, with direct model audio and no effects.
"""
from __future__ import annotations

from dataclasses import replace
import json
import re

from answer_tts import ROOT, TTSEngine
from project_paths import DATA, audio_root

OUTPUT = audio_root('edited')
PROFILE = {'delivery_profile': 'punctuation_only', 'delivery_version': 2, 'audio_processing': 'none'}


def word_sequence(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)*", text.lower())


def emphasize_answers(answers):
    overrides = json.loads((DATA / 'punctuation_overrides.json').read_text(encoding='utf-8'))
    result = []
    for answer in answers:
        vignette = re.search(r'Video Vignette (\d+)', answer.source)
        key = f'{int(vignette[1])}:{answer.index:03d}' if vignette else ''
        text = overrides.get(key, answer.spoken_text).strip()
        if text and text[-1] not in '.!?':
            text += '.'
        if word_sequence(text) != word_sequence(answer.spoken_text):
            raise ValueError(f'Punctuation edit changed words in {key}: {text}')
        result.append(replace(answer, spoken_text=text, notes=answer.notes + [
            'Punctuation preset only. Direct model audio; no audio effects.'
        ]))
    return result


class EmphasizedTTSEngine(TTSEngine):
    """Compatibility name for existing notebooks/jobs; applies no audio effects.
"""
    render_settings = PROFILE
