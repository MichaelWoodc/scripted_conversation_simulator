"""Guard compatibility between Kokoro runtime inputs and ONNX export types."""
from types import SimpleNamespace
import unittest
import numpy as np
from generate_all_voices import TypedModelSession


class FakeSession:
    def __init__(self, speed_type):
        self.speed_type = speed_type

    def get_inputs(self):
        return [SimpleNamespace(name='speed', type=self.speed_type),
                SimpleNamespace(name='input_ids', type='tensor(int64)')]

    def run(self, names, inputs):
        return inputs


class ModelInputTests(unittest.TestCase):
    def test_float_speed_graph_accepts_integer_runtime_input(self):
        session = TypedModelSession(FakeSession('tensor(float)'))
        result = session.run(None, {'speed': np.array([1], dtype=np.int32), 'input_ids': [[0, 1]]})
        self.assertEqual(result['speed'].dtype, np.float32)
        self.assertEqual(result['input_ids'].dtype, np.int64)

    def test_float_speed_preserves_fractional_values(self):
        session = TypedModelSession(FakeSession('tensor(float)'))
        result = session.run(None, {'speed': [1.15]})
        self.assertAlmostEqual(float(result['speed'][0]), 1.15, places=6)

    def test_integer_speed_graph_keeps_integer_input(self):
        session = TypedModelSession(FakeSession('tensor(int32)'))
        result = session.run(None, {'speed': [1]})
        self.assertEqual(result['speed'].dtype, np.int32)
