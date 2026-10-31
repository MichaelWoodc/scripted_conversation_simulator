"""Generate a short comparison clip for every Kokoro speaker, not full sessions."""
import hashlib
import json

from generate_all_voices import TypedModelSession, download, valid
from project_paths import ROOT, DIST


def generate():
    import soundfile as sf
    from kokoro_onnx import Kokoro
    config = json.loads((ROOT / 'data' / 'voice_sample_settings.json').read_text())
    voices = json.loads((ROOT / 'data' / 'kokoro_voices.json').read_text())
    cache = ROOT / '.cache' / 'kokoro-onnx'
    cache.mkdir(parents=True, exist_ok=True)
    release = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
    for name in ['kokoro-v1.0.onnx', 'voices-v1.0.bin']:
        download(release + name, cache / name)
    model = Kokoro(str(cache / 'kokoro-v1.0.onnx'), str(cache / 'voices-v1.0.bin'))
    model.sess = TypedModelSession(model.sess)
    output = DIST / 'media' / 'voice-samples'
    output.mkdir(parents=True, exist_ok=True)
    for index, voice in enumerate(voices, 1):
        path = output / (voice['id'] + '.wav')
        metadata = path.with_suffix('.json')
        settings = {**config, 'voice': voice['id'], 'language': 'en-gb' if voice['id'].startswith('b') else 'en-us'}
        fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        if valid(path) and metadata.exists() and json.loads(metadata.read_text()).get('fingerprint') == fingerprint:
            continue
        samples, rate = model.create(config['phrase'], voice=voice['id'], speed=config['speed'], lang=settings['language'])
        partial = path.with_suffix('.partial.wav')
        sf.write(str(partial), samples, rate, subtype='PCM_16')
        partial.replace(path)
        metadata.write_text(json.dumps({**settings, 'fingerprint': fingerprint}, indent=2), encoding='utf-8')
        print(f'{index}/{len(voices)} sample ready: {voice["id"]}', flush=True)
    from build_site import build
    build()
    print(f'All {len(voices)} samples ready: dist/voice-samples.html', flush=True)


if __name__ == '__main__':
    generate()
