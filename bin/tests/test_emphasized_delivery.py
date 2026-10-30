"""Ensure punctuation presets apply no waveform processing.
"""
from types import SimpleNamespace
import unittest
import numpy as np
import torch
from answer_tts import load_answers
from emphasized_delivery import EmphasizedTTSEngine, PROFILE, emphasize_answers, word_sequence


class DeliveryTests(unittest.TestCase):
    def test_all_answers_keep_words_and_numbering(self):
        original=load_answers()
        emphasized=emphasize_answers(original)
        self.assertEqual(len(emphasized),109)
        for before,after in zip(original,emphasized):
            self.assertEqual(word_sequence(before.spoken_text),word_sequence(after.spoken_text))
            self.assertEqual((before.source,before.index,before.raw_answer),(after.source,after.index,after.raw_answer))
        self.assertEqual(PROFILE['audio_processing'],'none')

    def test_model_samples_and_timing_are_unchanged(self):
        engine=object.__new__(EmphasizedTTSEngine)
        first=np.array([0.,0.2,-0.3,0.4,0.],dtype=np.float32)
        second=np.array([0.,-0.1,0.2,0.],dtype=np.float32)
        calls=[]
        def pipeline(text,**kwargs):
            calls.append(text)
            for samples in (first,second):
                yield SimpleNamespace(audio=torch.from_numpy(samples),tokens=[])
        engine.pipeline=lambda voice:pipeline
        output=engine.synthesize('Uh..... Um...',long_pause=True)
        np.testing.assert_array_equal(output,np.concatenate([first,second]))
        self.assertEqual(calls,['Uh..... Um...'])
        self.assertIs(engine.finish_audio(first,long_pause=True),first)
        self.assertIs(engine.adapt_chunk(SimpleNamespace(tokens=[]),first),first)


if __name__=='__main__':
    unittest.main()
