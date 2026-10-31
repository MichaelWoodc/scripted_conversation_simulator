"""Render each unique question with Windows TTS, then rebuild the static site."""
import argparse
import json
from pathlib import Path
import subprocess
import wave

from build_site import build, make_catalog, question_audio_path
from project_paths import ROOT


def generate(force=False):
    catalog, _ = make_catalog()
    prompts = dict.fromkeys(step['prompt'] for item in catalog['sets'] for step in item['steps'])
    requests = []
    for prompt in prompts:
        output = ROOT / 'dist' / question_audio_path(prompt)
        output.parent.mkdir(parents=True, exist_ok=True)
        valid = False
        if output.exists():
            try:
                with wave.open(str(output), 'rb') as audio:
                    valid = audio.getnframes() > 0
            except (wave.Error, EOFError):
                pass
        if force or not valid:
            requests.append({'text': prompt, 'path': str(output)})
    if requests:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                        str(Path(__file__).with_suffix('.ps1'))],
                       input=json.dumps(requests), text=True, check=True)
    build()
    print(f'{len(prompts)} unique questions ready; {len(requests)} synthesized.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Regenerate cached question recordings.')
    generate(parser.parse_args().force)
