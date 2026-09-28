"""Tests of scientific stop conditions, not evidence that a new run is valid."""
import json
from pathlib import Path
import unittest
from readiness import check_evidence


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = json.loads(Path(__file__).with_name("design.json").read_text())

    def adequate(self):
        return dict(independent_groups=80, traces=320, proved_fraction=.4,
                    unproved_fraction=.4, largest_truth_pattern_fraction=.5,
                    exit_rule_score=.6, invalid_tool_fraction=.01,
                    wrong_path_fraction=0, no_compile_fraction=0,
                    complete_review_fraction=1, disjoint_families=True,
                    unique_session_seeds=True, reviewer_qualified=True,
                    human_smoke_test_complete=True, power_calibration_passed=True,
                    challenge_coverage_passed=True, sun_coverage_passed=True)

    def failures(self, evidence):
        return {x["check"] for x in check_evidence(evidence, self.design)["checks"] if not x["passed"]}

    def test_missing_evidence_never_passes(self):
        result = check_evidence({}, self.design)
        self.assertFalse(result["diagnostic_checks_passed"])
        self.assertTrue(all(x["missing_evidence"] for x in result["checks"]))

    def test_legacy_collapse_rejected_despite_high_score(self):
        e = self.adequate()
        e.update(proved_fraction=0, largest_truth_pattern_fraction=113/120,
                 exit_rule_score=119/120)
        self.assertEqual(self.failures(e), {"proved coverage", "truth-pattern concentration", "exit-rule shortcut"})

    def test_more_samples_do_not_replace_groups(self):
        e = self.adequate()
        e.update(traces=10000, independent_groups=20)
        self.assertIn("independent evaluation groups", self.failures(e))

    def test_missing_prose_blocks_complete_targets(self):
        e = self.adequate()
        e["complete_review_fraction"] = 479/480
        self.assertIn("complete corrected reports", self.failures(e))

    def test_leakage_and_reused_seeds_block(self):
        e = self.adequate()
        e.update(disjoint_families=False, unique_session_seeds=False)
        self.assertEqual(self.failures(e), {"disjoint template families", "unique session seeds"})

    def test_string_true_is_not_an_attestation(self):
        e = self.adequate()
        e["human_smoke_test_complete"] = "true"
        self.assertIn("human smoke test", self.failures(e))

    def test_data_check_is_not_a_launch_certificate(self):
        result = check_evidence(self.adequate(), self.design)
        self.assertTrue(result["diagnostic_checks_passed"])
        self.assertFalse(result["ready_for_new_paid_run"])
        self.assertTrue(result["implementation_blockers"])


if __name__ == "__main__":
    unittest.main()
