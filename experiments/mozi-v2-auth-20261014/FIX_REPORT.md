# R1–R4 actual repair / local acceptance

2026-10-14. Parent evidence commit: efc2efc10007bb5797be26c13879a61c82eed394; original candidate: 0cec724f29455e5bf14c7efe0bf605eca0fd9c29. Only experiments/mozi-v2-auth-20261014 is changed on kr/mozi-r1-r4-fix-20261014. Local checkout is a separately initialized snapshot, not a checkout of main. Its snapshot commit is not represented as the upstream parent; the submitted GitHub commit uses the exact evidence commit as parent.

## Implemented

- R1: POST and GET metadata must both bind the positive integer comment ID, configured positive integer RESULT author, exact repository/issue API URL, exact comment API URL and body. Missing author configuration refuses publication. Fixed HTTPS GitHub API transport rejects redirects, unexpected final URLs, unrecognized paths and #20 writes. Injected APIs are a trusted local testing seam, not an untrusted plugin security boundary.
- R2: metadata containers and positive integer IDs are checked before use (booleans are not IDs). Each task has an exception boundary and durable HOLD audit; malformed tasks do not block later tasks. Refresh number is bound to the listed task. Global list exceptions propagate and non-list responses raise HOLD, never become an empty queue.
- R3: removed executor_sha256 constructor override. SHA256 is read from actual source bytes before state initialization. Optional expected_sha256 mismatch prevents even ledger creation. Python <3.12 is refused explicitly.
- R4: SQLite WAL/FULL durable audit commits before authorization can cause execution, and on rejection. Records contain timestamp, configured repository/API source, validated numeric issue reference, canonical input digest, fixed reason and execution state; never raw payloads, signatures, secrets, or arbitrary exception messages. Each event has a recomputable SHA256. Audit failure latches the instance closed and prevents execution. Ledger hashes detect accidental alteration; they are not signatures against a privileged ledger attacker.
- POSIX fsync covers state parent, state directory after ledger initialization/task-directory creation, and task directory after file creation. State parent must already exist. Windows does not claim POSIX directory durability.

## Actual tests and evidence

Local Windows / Python 3.12.14, temporary directories, synthetic signing key and fake API only. No network entrypoint is installed. Tests perform actual file creation, readback/hash, SQLite persistence, thread contention and a fresh Python subprocess restart.

red-final.log: final security suite against the retrieved old daemon/test fixture, exit 1, 9 tests, failures=8/errors=6 (subtests included). Errors include the missing audit table and expected-digest API, not an environment setup failure. Original review-probe.log remains historical evidence, not a post-fix PASS.

green.log: same security suite plus all original 11 behavioral groups, exit 0, 20 tests, OK. The original successful RESULT fixture now supplies the metadata required by R1; behavior/assertions remain. Added tests cover wrong ID/author/source, transport endpoint, malformed metadata, scan continuation, global outage, forbidden override, digest mismatch before state creation, independently reopened durable audit/hash and audit failure zero execution.

run_tests.py captures raw stdout/stderr and preserves child exit status. red.log is the initial development red run; red-final.log is the final baseline run. SHA256SUMS.json identifies delivered bytes. changes.diff compares the verified snapshot with final source/test changes.

## Remaining risks / limits

Local regression PASS is not cloud acceptance or production authorization. Linux power loss/fsync semantics, disk full, kill timing, ownership/ancestor permissions, symlink races, filesystem/SQLite durability, quotas, clock trust, key management and real GitHub API behavior remain unverified. Source measurement assumes trusted immutable code installation; it does not defeat replacement after import. Audit hash is unkeyed and requires protected storage/export to resist malicious modification. Ambiguous claims/POST attempts remain HOLD and are never blindly retried. No new network execution entrypoint or automatic service lifecycle was added.

## Next KR_GATE (prepare only; do not execute)

- [ ] Fix reviewed remote commit SHA and deployment file hashes; independent reviewer recomputes them.
- [ ] Explicitly approve a dedicated Linux host, isolated directory, Python 3.12+, nonprivileged UID, protected state parent/ledger and disk quota.
- [ ] Register trusted signer numeric ID and RESULT numeric author ID; key/token references only, least-privilege repository/API scope, trusted management channel and clock-skew limit.
- [ ] Approve dedicated simulation Issue, API write scope, acceptance window, start/stop commands, rollback conditions and proof of zero changes to old services.
- [ ] Run Linux crash/restart, disk-full, symlink/permission and directory durability tests; separately authorize real GitHub simulation POST/GET identity/source closure.
- [ ] Verify raw file hashes and task/run/issue/code/host/PID linkage. Production deployment and real-task authorization need another gate.

No main edit, production Daemon change, automatic pull/restart, production credentials, cloud access/deployment, #20 mutation, or TASK-REAL-042 execution occurred. #20 remains subject to open/HOLD/execution_authorized=false; this patch grants no authority to change it.
