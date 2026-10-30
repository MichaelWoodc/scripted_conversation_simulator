"""Check answer boundaries and ordering before a long audio generation job.
"""
import unittest
from collections import Counter

from answer_tts import clean_text, load_answers, parse_script


class ScriptTests(unittest.TestCase):
    def test_merged_labels_and_inline_answer(self):
        result = parse_script('QUESTION\nWhen?ANSWER\nNow.QUESTION: Why?\nANSWER: Because.', 'test.docx')
        self.assertEqual([a.spoken_text for a in result], ['Now.', 'Because.'])
        self.assertEqual([a.question for a in result], ['When?', 'Why?'])

    def test_label_attached_to_word(self):
        result = parse_script('QUESTION Start?ANSWER Not hereQUESTION Next?ANSWER Yes.', 'test.docx')
        self.assertEqual([a.spoken_text for a in result], ['Not here', 'Yes.'])

    def test_conditional_and_consecutive_answers(self):
        result = parse_script('QUESTION If asked:\nANSWER (annoyed): Maybe?\nANSWER\nYes.', 'test.docx')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].cues, ['annoyed'])
        self.assertEqual(result[0].spoken_text, 'Maybe?')
        self.assertEqual(result[1].index, 2)

    def test_stage_directions_are_not_spoken(self):
        result = parse_script('QUESTION Ready?ANSWER (Long pause) Um, no. (firmly) No.', 'test.docx')[0]
        self.assertEqual(result.cues, ['Long pause', 'firmly'])
        self.assertEqual(result.spoken_text, 'Um, no. No.')

    def test_multi_paragraph_answer(self):
        result = parse_script('QUESTION Ready?\nANSWER\nFirst thought.\nSecond thought.\nQUESTION Done?', 'test.docx')[0]
        self.assertEqual(result.spoken_text, 'First thought. Second thought.')

    def test_missing_or_empty_answers_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_script('Unlabelled text', 'test.docx')
        with self.assertRaises(ValueError):
            parse_script('QUESTION Hello?ANSWER QUESTION Next?', 'test.docx')

    def test_punctuation_preserves_words(self):
        result, _ = clean_text('They\u2019re here\u2026yes.')
        self.assertEqual(result, "They're here... yes.")

    def test_actual_document_counts_and_order(self):
        answers = load_answers()
        self.assertEqual(list(Counter(a.source for a in answers).values()), [38, 28, 43])
        self.assertEqual(answers[0].spoken_text, 'Ok.')
        self.assertEqual(answers[-1].spoken_text, 'Ok.')
        for source in dict.fromkeys(a.source for a in answers):
            indices = [a.index for a in answers if a.source == source]
            self.assertEqual(indices, list(range(1, len(indices) + 1)))
        for answer in answers:
            self.assertNotIn('QUESTION', answer.spoken_text)
            self.assertNotIn('ANSWER', answer.spoken_text)


if __name__ == '__main__':
    unittest.main()
