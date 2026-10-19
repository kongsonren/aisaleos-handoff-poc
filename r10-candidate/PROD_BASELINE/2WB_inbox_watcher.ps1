<#
.SYNOPSIS
  2WB GitHub Inbox Watcher - minimal unattended auto-receive + fixed ACK.
  Reuses proven R2 wincred CredRead pattern. No secret printing. Idempotent via state file.
  DO NOT run manually to "prove" AUTO_RECEIVE; let LocalAutomationScheduler trigger it.
#>
param([switch]$DryRun)

$ErrorActionPreference = 'Continue'

# ---------- config ----------
$repo        = "kongsonren/aisaleos-handoff-poc"
$inboxIssue  = 8
$triggerPrefix = "[TO-2WB]"
$ackPrefix     = "[ACK-2WB]"
$taskPrefixes  = @("[TO-2WB]","[TASK]","[GOVERNANCE]","[DIAG]")
$workDir     = "$env:USERPROFILE/.workbuddy/github_inbox_watcher"
$stateFile   = "$workDir/state.json"
$logFile     = "$workDir/watcher.log"
if (-not (Test-Path $workDir)) { New-Item -ItemType Directory -Path $workDir -Force | Out-Null }

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    "$ts | $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

# ---------- read credential from wincred (proven R2 pattern, no secret print) ----------
$credCode = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Cred {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags; public uint Type; public string TargetName; public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize; public IntPtr CredentialBlob; public uint Persist;
        public uint AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName;
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredRead(string target, uint type, uint reserved, out IntPtr pCred);
    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern void CredFree(IntPtr pCred);
}
'@
Add-Type -TypeDefinition $credCode -ErrorAction SilentlyContinue

$token = $null
foreach ($t in @("api.github.com/kongsonren","git:https://github.com","https://github.com/")) {
    $p = [IntPtr]::Zero
    if ([Cred]::CredRead($t, 1, 0, [ref]$p)) {
        $c = [System.Runtime.InteropServices.Marshal]::PtrToStructure($p, [type][Cred+CREDENTIAL])
        $b = New-Object byte[] $c.CredentialBlobSize
        [System.Runtime.InteropServices.Marshal]::Copy($c.CredentialBlob, $b, 0, $c.CredentialBlobSize)
        $token = [System.Text.Encoding]::UTF8.GetString($b) -replace '[^\x20-\x7E]',''
        [Cred]::CredFree($p)
        break
    }
}
if (-not $token) { Log "CRED_FOUND=NO (watcher cannot post; will retry next run)"; exit 0 }
Log "CRED_FOUND=YES TOKEN_LEN=$($token.Length) DRYRUN=$DryRun"

$headers = @{ Authorization = "token $token"; "User-Agent" = "2WB-InboxWatcher" }
$ua = @{ "User-Agent" = "2WB-InboxWatcher" }

# ---------- load state ----------
$acked = @{}
if (Test-Path $stateFile) {
    try {
        $parsed = Get-Content $stateFile -Raw -Encoding utf8 | ConvertFrom-Json
        if ($parsed) { $parsed.PSObject.Properties | ForEach-Object { $acked[$_.Name] = $_.Value } }
    } catch { $acked = @{} }
}
if (-not $acked.ContainsKey('acked')) { $acked['acked'] = @() }
if (-not $acked.ContainsKey('resulted')) { $acked['resulted'] = @() }

# ---------- fetch comments (paginated: fix RC3 - must reach deep-history task comments) ----------
$comments = @()
$page = 1
while ($true) {
    try {
        $paged = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/issues/$inboxIssue/comments?per_page=100&page=$page" -Headers $ua -TimeoutSec 30
    } catch {
        Log "FETCH_FAIL error=$($_.Exception.Message)"
        exit 0
    }
    if ($paged.Count -eq 0) { break }
    $comments += $paged
    if ($paged.Count -lt 100) { break }
    $page++
    if ($page -gt 50) { break }   # safety cap
}
Log "FETCH_OK total=$($comments.Count) pages=$page"

# ---------- RC4 fix: dedupe off existing GitHub ACK/RESULT comments (robust vs state-file truncation / read glitch) ----------
$alreadyAcked    = @{}
$alreadyResulted = @{}
foreach ($c in $comments) {
    $b = if ($c.body) { $c.body.Trim() } else { "" }
    if ($b.StartsWith("[ACK-2WB] trigger_comment_id=")) {
        $tid = ($b -replace '^\[ACK-2WB\] trigger_comment_id=','' -replace '\s.*$','').Trim()
        if ($tid) { $alreadyAcked[$tid] = $true }
    }
    if ($b -match '\[RESULT\]\[2WB\]\[[^\]]+\][\s\S]*trigger_comment_id=([0-9]+)') {
        $alreadyResulted[$Matches[1]] = $true
    }
}

# ---------- process ----------
$newAcks = 0
foreach ($c in $comments) {
    $cid = [string]$c.id
    if ($acked['acked'] -contains $cid -or $alreadyAcked.ContainsKey($cid)) { continue }
    $body = if ($c.body) { $c.body.Trim() } else { "" }
    if ($body.StartsWith($ackPrefix)) { $acked['acked'] += $cid; continue }   # skip own ACKs
    $isTrigger = $false
    foreach ($p in $taskPrefixes) { if ($body.StartsWith($p)) { $isTrigger = $true; break } }
    if (-not $isTrigger) { $acked['acked'] += $cid; continue }  # skip non-envelope (other prefixes)

    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $runId = Get-Date -Format "yyyyMMddHHmmss"
    $ackBody = "$ackPrefix trigger_comment_id=$cid received_at=$ts watcher_run=$runId"
    if ($isDecision) { $ackBody += " envelope=KR_DECISION receipt_only=TRANSPORT(no_auto_execute)" }

    if ($DryRun) {
        Log "DRYRUN would ACK trigger=$cid body_preview=$($body.Substring(0,[Math]::Min(40,$body.Length)))"
        $acked['acked'] += $cid
        $newAcks++
        continue
    }

    try {
        $resp = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/issues/$inboxIssue/comments" `
            -Method Post -Headers $headers -Body (@{ body = $ackBody } | ConvertTo-Json -Compress) `
            -ContentType "application/json" -TimeoutSec 30
        Log "ACK_POSTED trigger=$cid ack_comment_id=$($resp.id) ts=$ts"
        $acked['acked'] += $cid
        $newAcks++
        if ($body.StartsWith("[TASK]")) {
            $m = [regex]::Match($body, '\[TASK\]\[2WB\]\[([^\]]+)\]')
            $taskId = if ($m.Success) { $m.Groups[1].Value } else { "UNKNOWN" }
            if ($acked['resulted'] -notcontains $cid -and -not $alreadyResulted.ContainsKey($cid)) {
                $resultBody = "[RESULT][2WB][$taskId]`ntrigger_comment_id=$cid`nreceived_at=$ts`nstatus=REGISTERED`nNOTE=inbox-received-registered; business execution is a separate flow and not performed by this watcher"
                try {
                    $r2 = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/issues/$inboxIssue/comments" `
                        -Method Post -Headers $headers -Body (@{ body = $resultBody } | ConvertTo-Json -Compress) `
                        -ContentType "application/json" -TimeoutSec 30
                    Log "RESULT_POSTED task_id=$taskId trigger=$cid result_comment_id=$($r2.id) ts=$ts"
                    $acked['resulted'] += $cid
                } catch {
                    Log "RESULT_FAIL task_id=$taskId trigger=$cid error=$($_.Exception.Message)"
                }
            }
        }
    } catch {
        Log "ACK_FAIL trigger=$cid error=$($_.Exception.Message)"
        # leave unacked so next run retries
    }
}

# ---------- save state (auxiliary; primary dedupe is now GitHub ACK/RESULT scan above. Bounded to 5000 to avoid unbounded growth) ----------
$acked['acked'] = @($acked['acked'] | Select-Object -Last 5000)
$acked['resulted'] = @($acked['resulted'] | Select-Object -Last 5000)
$acked | ConvertTo-Json -Compress | Set-Content $stateFile -Encoding utf8
Log "DONE new_acks=$newAcks total_acked=$($acked['acked'].Count)"

# ---------- 2WB CLOCK Issue reporter (reuse wincred + same inbox Issue #8; idempotent by source hash) ----------
try {
    $clockFile = "$env:USERPROFILE/2WB_CLOCK_LATEST.md"
    $clockStateFile = "$workDir/clock_state.json"
    if (Test-Path $clockFile) {
        $cfHash = (Get-FileHash -Algorithm SHA256 $clockFile).Hash
        $clockState = @{}
        if (Test-Path $clockStateFile) { try { $parsed = Get-Content $clockStateFile -Raw -Encoding utf8 | ConvertFrom-Json; $clockState = @{}; if ($parsed) { $parsed.PSObject.Properties | ForEach-Object { $clockState[$_.Name] = $_.Value } } } catch { $clockState = @{} } }
        if ($clockState['last_hash'] -ne $cfHash) {
            $genTs = (Get-Item $clockFile).LastWriteTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            $clockBody = "[CLOCK][2WB]GENERATED_AT=$genTs" + "NODE=2WB STATUS_SOURCE=C:\Users\59605\2WB_CLOCK_LATEST.md SOURCE_HASH=$cfHash" + "KR_MANUAL_RUN=0 KR_RELAY=0 HAI_RELAY=0"
            if ($DryRun) {
                Log "CLOCK_DRYRUN hash=$cfHash"
                $clockState['last_hash'] = $cfHash
                $clockState | ConvertTo-Json -Compress | Set-Content $clockStateFile -Encoding utf8
            } else {
                $cresp = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/issues/$inboxIssue/comments" `
                    -Method Post -Headers $headers -Body (@{ body = $clockBody } | ConvertTo-Json -Compress) `
                    -ContentType "application/json" -TimeoutSec 30
                Log "CLOCK_POSTED comment_id=$($cresp.id) hash=$cfHash ts=$genTs"
                $clockState['last_hash'] = $cfHash
                $clockState['last_comment_id'] = [string]$cresp.id
                $clockState['last_ts'] = $genTs
                $clockState | ConvertTo-Json -Compress | Set-Content $clockStateFile -Encoding utf8
            }
        } else {
            Log "CLOCK_SKIP unchanged hash=$cfHash"
        }
    } else {
        Log "CLOCK_SKIP no clock file"
    }
} catch {
    Log "CLOCK_FAIL error=$($_.Exception.Message)"
}
exit 0
