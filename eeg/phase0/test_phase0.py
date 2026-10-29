"""Offline tests for phase0_record.py (no headset needed): py -m unittest test_phase0"""

import json
import tempfile
import unittest
from pathlib import Path

import phase0_record as p0


def run_mock(tmp, effect):
    return p0.main(["--mock", "--yes", "--open-seconds", "3", "--closed-seconds", "3",
                    "--settle", "0.5", "--mock-alpha-effect", str(effect), "--out", tmp])


class Phase0Tests(unittest.TestCase):
    def test_berger_pass_and_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_mock(tmp, 2.5), 0)
            summary = json.loads(next(Path(tmp).glob("*_summary.json")).read_text())
            self.assertEqual(sorted(summary["streams_allowed"]), ["eq", "mot", "pow"])
            self.assertIn("eeg", summary["streams_refused"])
            self.assertEqual(summary["berger_check"]["verdict"], "PASS")
            header = next(Path(tmp).glob("*_pow.csv")).read_text().splitlines()[0]
            self.assertTrue(header.startswith("cortex_time,host_time,phase,phase_elapsed_s,AF3/theta"))
            self.assertFalse(list(Path(tmp).glob("*_eeg.csv")))

    def test_no_effect_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_mock(tmp, 0.6), 2)
            pow_csv = next(Path(tmp).glob("*_pow.csv"))
            self.assertEqual(p0.analyze(pow_csv, 0.5)["verdict"], "FAIL")

    def test_phase_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_mock(tmp, 2.5)
            text = next(Path(tmp).glob("*_mot.csv")).read_text()
            for label in ("eyes_open", "eyes_closed"):
                self.assertIn(f",{label},", text)


if __name__ == "__main__":
    unittest.main()
