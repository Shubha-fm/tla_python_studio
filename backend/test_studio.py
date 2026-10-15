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
        self.assertTrue(all(edge.get('action') in ('Increment','Reset') for edge in result['edges']))
        self.assertEqual(result['summary']['property_status'],'pass_finite_graph')

    def test_counterexample(self):
        result=verify(SOURCE,'count < 2')
        self.assertEqual(result['summary']['property_status'],'violation')
        self.assertTrue(result['counterexample'])

    def test_unchanged_variable(self):
        source = """---- MODULE Pair ----
VARIABLES count, flag
Init == /\\ count = 0
        /\\ flag = TRUE
Step == /\\ count < 2
        /\\ count' = count + 1
        /\\ UNCHANGED flag
Next == Step
===="""
        result=verify(source,'flag = TRUE')
        self.assertEqual(result['summary']['states'],3)
        self.assertEqual(result['summary']['deadlocks'],1)

    def test_invalid_input(self):
        with self.assertRaises(TranslationError):
            tla_to_python_from_string('INVALID')

if __name__=='__main__':
    unittest.main()
