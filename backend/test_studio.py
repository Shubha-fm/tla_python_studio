import unittest
from tla_parser import tla_to_python_from_string, TranslationError
from verification import verify

SOURCE = """---- MODULE Counter ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Increment == /\\ count < 3
             /\\ count' = count + 1
Reset == /\\ count = 3
         /\\ count' = 0
Next == Increment \\/ Reset
===="""

class StudioTests(unittest.TestCase):
    def test_translator(self):
        output=tla_to_python_from_string(SOURCE)
        self.assertIn('INITIAL_STATE',output)
        self.assertIn('def next_states',output)

    def test_graph(self):
        result=verify(SOURCE,'count >= 0')
        self.assertEqual(result['summary']['states'],4)
        self.assertEqual(result['summary']['transitions'],4)
        self.assertEqual(result['summary']['property_status'],'pass_finite_graph')

    def test_counterexample(self):
        result=verify(SOURCE,'count < 2')
        self.assertEqual(result['summary']['property_status'],'violation')
        self.assertTrue(result['counterexample'])

    def test_invalid_input(self):
        with self.assertRaises(TranslationError):
            tla_to_python_from_string('INVALID')

if __name__=='__main__':
    unittest.main()
