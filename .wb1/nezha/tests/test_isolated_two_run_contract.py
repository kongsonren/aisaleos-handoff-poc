"""Unit tests for isolated two-run evidence contract (no network)."""
import unittest
from isolated_two_run_contract import ChainEvidence, verdict

def sample(**overrides):
    data = dict(first_run_id=100, second_run_id=101, second_triggered_by_first=True,
                branch_isolated=True, business_steps_skipped=True, state_separate=True,
                first_dispatch_http=204, second_run_completed=True)
    data.update(overrides)
    return ChainEvidence(**data)

class TestTwoRunContract(unittest.TestCase):
    def test_valid_evidence(self):
        self.assertEqual(verdict(sample()), "PASS_NARROW_TWO_RUN_CHAIN")
    def test_same_run_rejected(self):
        self.assertEqual(verdict(sample(second_run_id=100)), "FAIL_MISSING_DISTINCT_RUNS")
    def test_missing_chain_rejected(self):
        self.assertEqual(verdict(sample(second_triggered_by_first=False)), "FAIL_NO_MACHINE_CHAIN")
    def test_business_risk_rejected(self):
        self.assertEqual(verdict(sample(business_steps_skipped=False)), "FAIL_UNSAFE")
    def test_shared_state_rejected(self):
        self.assertEqual(verdict(sample(state_separate=False)), "FAIL_UNSAFE")
    def test_pending_is_not_pass(self):
        self.assertEqual(verdict(sample(second_run_completed=False)), "UNKNOWN_PENDING")

if __name__ == "__main__":
    unittest.main()
