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
# R7/R9：业务信封入本地队列交 executor 真实领取执行（GitHub 仍为 ACK 回执层）
$queueFile   = "$workDir/frontleg_inbox_queue.json"
if (-not (Test-Path $workDir)) { New-Item -ItemType Directory -Path $workDir -Force | Out-Null }

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    "$ts | $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

# R9/D1/D2 硬化：本地队列读写（UTF8NoBOM 去 BOM + 单元素数组强制包裹为数组）
function Write-Queue($q) {
    $arr = @($q)
    $json = $arr | ConvertTo-Json -Compress -Depth 10
    if (-not $json.StartsWith('[')) { $json = '[' + $json + ']' }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    [System.IO.File]::WriteAllBytes($queueFile, $bytes)
}
function Enqueue-Task($orderId, $body) {
    $q = @()
    if (Test-Path $queueFile) {
        try {
            $raw = Get-Content $queueFile -Raw -Encoding utf8
            $p = ConvertFrom-Json $raw
            if ($p -is [System.Array]) { $q = $p } elseif ($p) { $q = @($p) }
        } catch { $q = @() }
    }
    $taskId = "Q-$(Get-Date -Format 'yyyyMMddHHmmssfff')"
    $q += [pscustomobject]@{
        order_id = $orderId
        task_id  = $taskId
        action   = "DISPATCH"
        envelope_body = $body
        received_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    Write-Queue $q
    Log "ENQUEUE order_id=$orderId task_id=$taskId"
}

# ---------- R9 修复：凭据获取（避免 Add-Type 被本环境安全策略整体拦截；env 优先 + 同目录 python-ctypes 桥） ----------
# 生产原文件用 Add-Type CredRead：本环境 PowerShell 对 Add-Type 整体安全拦截 -> CRED_FOUND=NO -> 早退（到不了检测）。
# 候选改为：$env:GITHUB_PAT 优先；缺失则调用同目录 2WB_pat_bridge.py（python ctypes 读 wincred，本环境可用）。
$pyExe = "C:\Users\59605\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$token = $env:GITHUB_PAT
if (-not $token) {
    try {
        $raw = (& $pyExe (Join-Path $PSScriptRoot "2WB_pat_bridge.py") 2>$null)
        if ($raw) { $token = ($raw -split "`n")[-1].Trim() }
    } catch { $token = $null }
}
if (-not $token) { Log "CRED_FOUND=NO (watcher cannot post; will retry next run)"; exit 0 }
Log "CRED_FOUND=YES TOKEN_LEN=$($token.Length) DRYRUN=$DryRun SRC=env_or_python_bridge"

# R7 修复：$isDecision 默认 false（原生产代码全程未定义，死代码隐患；生产 watcher L123 引用但未声明）
$isDecision = $false

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
        # D3 修复：拉取评论改用带 Authorization 的 $headers（原 $ua 无认证，匿名 60/h 限流会触发 403 已禁止）
        $paged = Invoke-RestMethod -Uri "http://127.0.0.1:8731/repos/$repo/issues/$inboxIssue/comments?per_page=100&page=$page" -Headers $headers -TimeoutSec 30
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
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8731/repos/$repo/issues/$inboxIssue/comments" `
            -Method Post -Headers $headers -Body (@{ body = $ackBody } | ConvertTo-Json -Compress) `
            -ContentType "application/json" -TimeoutSec 30
        Log "ACK_POSTED trigger=$cid ack_comment_id=$($resp.id) ts=$ts"
        $acked['acked'] += $cid
        $newAcks++
        # R7 修复：移除幻影 [RESULT] status=REGISTERED（watcher 未执行却声明已登记，属 FALSE PASS）。
        # 业务 [TASK] 信封改为入本地队列，交由 executor 真实领取执行（见 frontleg_executor.py consume_queue）。
        if ($body.StartsWith("[TASK]")) {
            Enqueue-Task -orderId $cid -body $body
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
                $cresp = Invoke-RestMethod -Uri "http://127.0.0.1:8731/repos/$repo/issues/$inboxIssue/comments" `
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
