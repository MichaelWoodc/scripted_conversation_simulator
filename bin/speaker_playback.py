"""Notebook speaker selection and playback through a named output device.
"""
from html import escape
import io
import json
from pathlib import Path

import ipywidgets as W
import numpy as np
import sounddevice as sd
import soundfile as sf


class SpeakerPlayback:
    def __init__(self, output):
        self.preferences = Path(output) / 'playback.json'
        self._refreshing = False
        self.devices = {}
        self.device = W.Dropdown(options=[('System default', None)], value=None, description='Speaker:',
                                 layout=W.Layout(width='100%', max_width='650px'))
        self.test_button = W.Button(description='Test speaker', icon='volume-up')
        self.refresh_button = W.Button(description='Refresh speakers', icon='refresh')
        self.status = W.HTML()
        self.device.observe(self._changed, names='value')
        self.test_button.on_click(lambda _: self.test())
        self.refresh_button.on_click(lambda _: self.refresh())
        self.widget = W.VBox([self.device, W.HBox([self.test_button, self.refresh_button]), self.status])
        self.refresh()

    def refresh(self):
        self._refreshing = True
        try:
            apis = sd.query_hostapis()
            outputs = [(i, d, apis[d['hostapi']]['name']) for i, d in enumerate(sd.query_devices())
                       if d['max_output_channels'] > 0]
            # WASAPI exposes complete, untruncated names and supports system conversion.
            preferred = [d for d in outputs if d[2] == 'Windows WASAPI']
            if preferred:
                outputs = preferred
            self.devices = {i: {**dict(d), 'api_name': api} for i, d, api in outputs}
            try:
                default_name = sd.query_devices(kind='output')['name']
            except sd.PortAudioError:
                default_name = 'unavailable'
            options = [(f'System default - {default_name}', None)] + [(d['name'], i) for i, d, api in outputs]
            saved = json.loads(self.preferences.read_text(encoding='utf-8')) if self.preferences.exists() else {}
            selected = next((i for i, d in self.devices.items() if d['name'] == saved.get('name')
                             and d['api_name'] == saved.get('api')), None)
            self.device.options = options
            self.device.value = selected
            self.status.value = 'Choose your speakers or headphones, then use Test speaker.'
        except Exception as exc:
            self.status.value = 'Could not list speakers: ' + escape(str(exc))
        finally:
            self._refreshing = False

    def _changed(self, _):
        if self._refreshing:
            return
        info = self.devices.get(self.device.value, {})
        saved = {'name': info.get('name'), 'api': info.get('api_name')}
        self.preferences.parent.mkdir(parents=True, exist_ok=True)
        self.preferences.write_text(json.dumps(saved, indent=2), encoding='utf-8')
        self.status.value = 'Selected speaker: ' + escape(self.device.label)

    def parameters(self, rate):
        selected = self.device.value
        info = self.devices.get(selected) if selected is not None else sd.query_devices(kind='output')
        api = info.get('api_name') or sd.query_hostapis(info['hostapi'])['name']
        extra = sd.WasapiSettings(auto_convert=True) if api == 'Windows WASAPI' else None
        sd.check_output_settings(device=selected, channels=1, samplerate=rate, dtype='float32', extra_settings=extra)
        return {'device': selected, 'extra_settings': extra}

    def play_samples(self, samples, rate):
        parameters = self.parameters(rate)
        sd.play(samples, samplerate=rate, blocking=False, **parameters)
        return self.device.label

    def play(self, wav_bytes):
        samples, rate = sf.read(io.BytesIO(wav_bytes), dtype='float32')
        return self.play_samples(samples, rate)

    def test(self):
        try:
            rate = 24000
            times = np.arange(round(rate*0.35))/rate
            tone = (0.12*np.sin(2*np.pi*440*times)*np.sin(np.pi*times/0.35)**2).astype(np.float32)
            name = self.play_samples(tone, rate)
            self.status.value = 'Playing a short test tone through ' + escape(name)
        except Exception as exc:
            self.status.value = 'Speaker test failed: ' + escape(str(exc))

    @staticmethod
    def stop():
        sd.stop()
