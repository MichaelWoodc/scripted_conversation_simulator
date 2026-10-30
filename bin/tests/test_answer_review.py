"""Protect the editable preview/approve workflow and short-answer isolation.
"""
import asyncio
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from answer_review import AnswerEditor, AnswerReviewStudio, ReviewStore, preview_audio
from answer_tts import SAMPLE_RATE


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text, voice, speed, **kwargs):
        self.calls += 1
        t = np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE
        return (0.2 * np.sin(t*2*np.pi*220)).astype(np.float32)


class ReviewTests(unittest.TestCase):
    def test_save_uses_exact_preview_and_rejects_stale_edits(self):
        with TemporaryDirectory() as temp:
            engine = FakeEngine()
            studio = AnswerReviewStudio(output=temp, engine_factory=lambda _: engine)
            answer = studio.answers[3]
            settings = {'text': 'Um... instructions.', 'voice': 'af_heart', 'speed': 1.0,
                        'delivery': 'original', 'smooth_short_answers': False}
            preview = studio.generate(answer, settings)
            self.assertEqual(engine.calls, 1)
            path = studio.store.save(answer, preview, settings)
            self.assertEqual(path.read_bytes(), preview.wav_bytes)
            self.assertEqual(path.name, 'answer_004.wav')
            self.assertEqual(path.parent.name, Path(answer.source).stem)
            self.assertEqual(sf.info(str(path)).subtype, 'PCM_24')
            self.assertEqual(engine.calls, 1)
            with self.assertRaises(ValueError):
                studio.store.save(answer, preview, dict(settings, text='Changed text.'))
            self.assertEqual(path.read_bytes(), preview.wav_bytes)
            reloaded = ReviewStore(temp)
            self.assertEqual(reloaded.drafts[reloaded.key(answer)], settings)
            studio.executor.shutdown()

    def test_editor_buttons_and_drafts_are_independent(self):
        with TemporaryDirectory() as temp:
            studio = AnswerReviewStudio(output=temp, engine_factory=lambda _: FakeEngine())
            first, second = studio.answers[:2]
            studio.answer(first.source, first.index)
            studio.answer(second.source, second.index)
            a = studio.editors[(first.source, first.index)]
            b = studio.editors[(second.source, second.index)]
            self.assertEqual(a.text.value, 'Ok.')
            a.text.value = 'Okay!'
            self.assertEqual(b.text.value, 'Yes.')
            self.assertTrue(a.save_button.disabled)
            self.assertTrue(a.play_button.disabled)
            # Long text bypasses the real model's short-answer path in this widget test.
            a.text.value = 'Okay, that sounds right.'
            asyncio.run(a.generate_preview())
            self.assertFalse(a.save_button.disabled)
            self.assertFalse(a.play_button.disabled)
            self.assertEqual(bytes(a.audio_player.value), a._preview.wav_bytes)
            self.assertTrue(a.audio_player.controls)
            studio.play_on_pc = Mock(return_value='Selected speakers')
            a.play_button.click()
            studio.play_on_pc.assert_called_once_with(a.answer, a._preview)
            self.assertIn('Selected speakers', a.status.value)
            toolbar = next(child for child in a.widget.children if getattr(child, 'children', ())
                           and a.generate_button in child.children)
            self.assertEqual([w.description for w in toolbar.children],
                             ['Generate preview', 'Play preview', 'Save this preview'])
            saved = a.save_preview()
            self.assertIsNotNone(saved)
            a.voice.value = 'af_bella'
            self.assertTrue(a.save_button.disabled)
            self.assertTrue(a.play_button.disabled)
            self.assertEqual(bytes(a.audio_player.value), b'')
            self.assertIsNone(a.save_preview())
            self.assertEqual(ReviewStore(temp).drafts[studio.store.key(first)]['voice'], 'af_bella')
            studio.executor.shutdown()

    def test_text_and_audio_pass_through_without_effects(self):
        source = np.array([0., .2, -.25, .3, 0.], dtype=np.float32)
        engine = SimpleNamespace(synthesize=Mock(return_value=source))
        text = 'Uh..... Yes! Um... my own punctuation.'
        settings = {'text':text, 'voice':'af_heart', 'speed':1.0, 'smooth_short_answers':True}
        audio, details = preview_audio(engine, settings, long_pause=True)
        engine.synthesize.assert_called_once_with(text, 'af_heart', 1.0)
        self.assertIs(audio, source)
        self.assertEqual(details['rendered_text'], text)
        self.assertEqual(details['audio_processing'], 'none')

    def test_separate_notebooks_merge_their_drafts(self):
        with TemporaryDirectory() as temp:
            left, right = ReviewStore(temp), ReviewStore(temp)
            a, b = AnswerReviewStudio(output=temp).answers[:2]
            left.update_draft(a, {'text': 'Okay!'})
            right.update_draft(b, {'text': 'Yes!'})
            drafts = ReviewStore(temp).drafts
            self.assertEqual(drafts[left.key(a)]['text'], 'Okay!')
            self.assertEqual(drafts[right.key(b)]['text'], 'Yes!')

    def test_playback_uses_selected_speaker_and_original_preview(self):
        with TemporaryDirectory() as temp:
            studio = AnswerReviewStudio(output=Path(temp)/'reviewed', engine_factory=lambda _: FakeEngine())
            answer = studio.answers[3]
            settings = {'text':'Instructions.', 'voice':'af_heart', 'speed':1.0,
                        'delivery':'original', 'smooth_short_answers':False}
            preview = studio.generate(answer, settings)
            with patch.object(studio.playback, 'play', return_value='Selected speakers') as play:
                self.assertEqual(studio.play_on_pc(answer, preview), 'Selected speakers')
                play.assert_called_once_with(preview.wav_bytes)
            self.assertEqual(sf.info(io.BytesIO(preview.wav_bytes)).subtype, 'PCM_24')
            studio.executor.shutdown()

    def test_reload_replaces_existing_display_and_keeps_preview(self):
        from review_bootstrap import get_review_studio
        with TemporaryDirectory() as temp:
            old = AnswerReviewStudio(output=temp, engine_factory=lambda _: FakeEngine())
            answer = old.answers[3]
            root = old.answer(answer.source, answer.index)
            editor = old.editors[(answer.source, answer.index)]
            editor.text.value = 'My edited answer.'
            asyncio.run(editor.generate_preview())
            preview = editor._preview
            namespace = {'studio': old}
            new = get_review_studio(namespace)
            self.assertIsNot(new, old)
            updated = new.editors[(answer.source, answer.index)]
            self.assertIs(updated.widget, root)
            self.assertIs(updated._preview, preview)
            self.assertEqual(updated.text.value, 'My edited answer.')
            self.assertFalse(updated.play_button.disabled)
            self.assertIn(updated.play_button, root.children[4].children)
            self.assertIs(get_review_studio(namespace), new)
            new.executor.shutdown()


if __name__ == '__main__':
    unittest.main()
