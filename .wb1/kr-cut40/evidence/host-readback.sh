#!/bin/sh
# Prepared only. Run through the existing verified SSH channel; no credentials read.
set -eu
hostname
id
systemctl show kr-isolated-daemon-20261013 -p ActiveState -p SubState -p MainPID -p NRestarts -p DynamicUser -p ExecStart -p StateDirectory
sha256sum /opt/kr-isolated-daemon-20261013/daemon.py
stat -c '%U %G %a %n' /opt/kr-isolated-daemon-20261013 /var/lib/kr-isolated-daemon-20261013
sha256sum /var/lib/kr-isolated-daemon-20261013/issue-18-CLOUD-DAEMON-20261014-02/test.txt
# Limit output to typed audit events; no EnvironmentFile or /proc environment reads.
grep -E '"event": "(START|SCAN|SCAN_ERROR|TASK_ERROR|RESULT_VERIFIED|POST_AMBIGUOUS_HOLD)"' /var/lib/kr-isolated-daemon-20261013/ledger.jsonl | tail -n 30
