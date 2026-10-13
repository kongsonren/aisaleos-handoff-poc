"""Isolated self-schedule test contract. No GitHub calls or business execution.

This file defines the acceptance gates for a future two-run sandbox test.
It deliberately cannot dispatch workflows or reset production heartbeat.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ChainEvidence:
    first_run_id: int
    second_run_id: int
    second_triggered_by_first: bool
    branch_isolated: bool
    business_steps_skipped: bool
    state_separate: bool
    first_dispatch_http: int
    second_run_completed: bool

def verdict(e: ChainEvidence) -> str:
    if not e.branch_isolated or not e.business_steps_skipped or not e.state_separate:
        return "FAIL_UNSAFE"
    if e.first_run_id <= 0 or e.second_run_id <= 0 or e.first_run_id == e.second_run_id:
        return "FAIL_MISSING_DISTINCT_RUNS"
    if e.first_dispatch_http != 204 or not e.second_triggered_by_first:
        return "FAIL_NO_MACHINE_CHAIN"
    if not e.second_run_completed:
        return "UNKNOWN_PENDING"
    return "PASS_NARROW_TWO_RUN_CHAIN"
