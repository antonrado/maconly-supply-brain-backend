param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("up", "ps", "logs", "test", "health", "proposal", "po-api-smoke", "context", "verify", "verify-live")]
    [string]$Command
)

$ComposeFile = ".\\docker-compose.yml"

function Get-ContextBaseRef {
    $BaseRef = git merge-base HEAD origin/main 2>$null
    if (-not $BaseRef) {
        return "HEAD~1"
    }

    return $BaseRef.Trim()
}

function Invoke-ContextGuard {
    $BaseRef = Get-ContextBaseRef
    python .\scripts\context_guard.py --base $BaseRef --head HEAD
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-CompileCheck {
    python -m compileall app tests scripts alembic
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Wait-BackendRunning {
    param(
        [int]$TimeoutSeconds = 30
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        $RunningServices = docker compose -f $ComposeFile ps --status running --services 2>$null
        $BackendRunning = $LASTEXITCODE -eq 0 -and (($RunningServices | ForEach-Object { $_.Trim() }) -contains "backend")
        if ($BackendRunning) {
            return $true
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Wait-ApiHealthy {
    param(
        [string]$Url = "http://localhost:8000/api/v1/planning/core/health",
        [int]$ExpectedStatus = 200,
        [int]$TimeoutSeconds = 30
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        $ResponseFile = [System.IO.Path]::GetTempFileName()
        try {
            $StatusCode = curl.exe -sS -o $ResponseFile -w "%{http_code}" -X GET $Url 2>$null
            if ($LASTEXITCODE -eq 0 -and "$StatusCode" -eq "$ExpectedStatus") {
                return $true
            }
        }
        finally {
            if (Test-Path $ResponseFile) {
                Remove-Item $ResponseFile -ErrorAction SilentlyContinue
            }
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Invoke-ApiExpectedStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [int]$ExpectedStatus,
        [string]$JsonBody = "",
        [string]$ExpectedBodyContains = ""
    )

    $ResponseFile = [System.IO.Path]::GetTempFileName()
    $PayloadFile = $null
    $ResponseBody = ""
    try {
        if ($JsonBody) {
            $PayloadFile = [System.IO.Path]::GetTempFileName()
            $JsonBody | Set-Content -Encoding utf8 -NoNewline $PayloadFile
            $StatusCode = curl.exe -sS -o $ResponseFile -w "%{http_code}" -X $Method $Url -H "Content-Type: application/json" --data-binary "@$PayloadFile"
        }
        else {
            $StatusCode = curl.exe -sS -o $ResponseFile -w "%{http_code}" -X $Method $Url
        }

        if ($LASTEXITCODE -ne 0) {
            Write-Host "[po-api-smoke] FAIL ${Name}: curl exited with code $LASTEXITCODE" -ForegroundColor Red
            if (Test-Path $ResponseFile) {
                Get-Content -Raw $ResponseFile | Write-Host
            }
            exit $LASTEXITCODE
        }

        if (Test-Path $ResponseFile) {
            $ResponseBody = Get-Content -Raw $ResponseFile
        }

        if ("$StatusCode" -ne "$ExpectedStatus") {
            Write-Host "[po-api-smoke] FAIL ${Name}: expected HTTP $ExpectedStatus, got HTTP $StatusCode" -ForegroundColor Red
            $ResponseBody | Write-Host
            exit 1
        }

        if ($ExpectedBodyContains -and -not $ResponseBody.Contains($ExpectedBodyContains)) {
            Write-Host "[po-api-smoke] FAIL ${Name}: response body does not include expected fragment '$ExpectedBodyContains'" -ForegroundColor Red
            $ResponseBody | Write-Host
            exit 1
        }

        Write-Host "[po-api-smoke] OK  $Name -> HTTP $StatusCode"
    }
    finally {
        if ($PayloadFile -and (Test-Path $PayloadFile)) {
            Remove-Item $PayloadFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $ResponseFile) {
            Remove-Item $ResponseFile -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-SmokeTests {
    $TargetTests = @(
        "tests/test_planning_core_production_order_api.py",
        "tests/test_planning_core_production_order_settings_api.py"
    )

    python -c "import pytest" 2>$null
    $HostPytestAvailable = $LASTEXITCODE -eq 0

    if ($HostPytestAvailable) {
        python -m pytest -q @TargetTests
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        return
    }

    $RunningServices = docker compose -f $ComposeFile ps --status running --services 2>$null
    $BackendRunning = $LASTEXITCODE -eq 0 -and (($RunningServices | ForEach-Object { $_.Trim() }) -contains "backend")

    if ($BackendRunning) {
        Write-Host "[verify] syncing backend image with current workspace..."
        docker compose -f $ComposeFile up -d --build backend
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        if (-not (Wait-BackendRunning -TimeoutSeconds 30)) {
            Write-Host "[verify] backend did not reach running state in time." -ForegroundColor Yellow
            exit 1
        }

        docker compose -f $ComposeFile exec -T backend python -c "import pytest, httpx" 2>$null
        $BackendTestDepsAvailable = $LASTEXITCODE -eq 0

        if (-not $BackendTestDepsAvailable) {
            Write-Host "[verify] backend test dependencies missing, installing..."
            docker compose -f $ComposeFile exec -T backend python -m pip install --disable-pip-version-check -q pytest httpx
            if ($LASTEXITCODE -ne 0) {
                exit $LASTEXITCODE
            }
        }

        docker compose -f $ComposeFile exec -T backend python -m pytest -q @TargetTests
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        return
    }

    Write-Host "verify: tests were not run (host pytest missing and backend container is not running)." -ForegroundColor Yellow
    Write-Host "Run '.\\scripts\\dev.ps1 up' or install pytest locally, then rerun '.\\scripts\\dev.ps1 verify'." -ForegroundColor Yellow
    exit 1
}

function Invoke-ProductionOrderApiSmoke {
    Write-Host "[po-api-smoke] syncing backend image with current workspace..."
    docker compose -f $ComposeFile up -d --build backend
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if (-not (Wait-BackendRunning -TimeoutSeconds 45)) {
        Write-Host "[po-api-smoke] backend did not reach running state in time." -ForegroundColor Yellow
        exit 1
    }

    if (-not (Wait-ApiHealthy -TimeoutSeconds 45)) {
        Write-Host "[po-api-smoke] health endpoint did not become ready in time." -ForegroundColor Yellow
        docker compose -f $ComposeFile logs --tail=80 backend
        exit 1
    }

    Invoke-ApiExpectedStatus -Name "planning-core-health" -Method "GET" -Url "http://localhost:8000/api/v1/planning/core/health" -ExpectedStatus 200

    $SeedOutput = docker compose -f $ComposeFile exec -T backend python scripts/po_api_smoke_seed.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[po-api-smoke] FAIL seed step: unable to prepare smoke dataset." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    try {
        $SeedData = $SeedOutput | ConvertFrom-Json
    }
    catch {
        Write-Host "[po-api-smoke] FAIL seed step: invalid seed JSON output." -ForegroundColor Red
        Write-Host $SeedOutput
        exit 1
    }

    $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
    $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress

    Invoke-ApiExpectedStatus -Name "production-order-direct-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 200 -JsonBody $DirectHappyPayload -ExpectedBodyContains '"status":"ok"'
    Invoke-ApiExpectedStatus -Name "production-order-from-wb-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -ExpectedBodyContains '"status":"ok"'

    $UnknownArticleDirectPayload = '{"article_id":999999999,"planning_horizon_days":90,"bundle_daily_sales":[{"bundle_type_id":1,"daily_sales":1.0}],"bundle_stock":[{"bundle_type_id":1,"wb_qty":0,"local_qty":0}],"in_flight_supply":[],"size_weights":{}}'
    Invoke-ApiExpectedStatus -Name "production-order-direct-unknown-article" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 404 -JsonBody $UnknownArticleDirectPayload -ExpectedBodyContains 'Article not found'

    $UnknownArticleFromWbPayload = '{"article_id":999999999,"planning_horizon_days":90,"observation_window_days":30,"bundle_type_ids":[1],"in_flight_supply":[],"size_weights":{}}'
    Invoke-ApiExpectedStatus -Name "production-order-from-wb-unknown-article" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 404 -JsonBody $UnknownArticleFromWbPayload -ExpectedBodyContains 'Article not found'

    $DirectInvalidPayload = '{"article_id":1,"planning_horizon_days":0,"bundle_daily_sales":[]}'
    Invoke-ApiExpectedStatus -Name "production-order-direct-validation" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 422 -JsonBody $DirectInvalidPayload -ExpectedBodyContains 'planning_horizon_days'

    $FromWbInvalidPayload = '{"article_id":1,"planning_horizon_days":90,"observation_window_days":30,"freshness_mode":"hard_fail","bundle_type_ids":[1],"in_flight_supply":[],"size_weights":{}}'
    Invoke-ApiExpectedStatus -Name "production-order-from-wb-validation" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 422 -JsonBody $FromWbInvalidPayload -ExpectedBodyContains 'freshness_mode'
}

switch ($Command) {
    "up" {
        docker compose -f $ComposeFile up -d --build
    }
    "ps" {
        docker compose -f $ComposeFile ps
    }
    "logs" {
        docker compose -f $ComposeFile logs --tail=200 backend
    }
    "test" {
        docker compose -f $ComposeFile exec -T backend python -m pytest -q
    }
    "health" {
        curl.exe -i http://localhost:8000/api/v1/planning/core/health
    }
    "proposal" {
        '{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
        curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
    }
    "po-api-smoke" {
        Invoke-ProductionOrderApiSmoke
    }
    "context" {
        Invoke-ContextGuard
    }
    "verify" {
        Write-Host "[verify] context guard..."
        Invoke-ContextGuard

        Write-Host "[verify] compile check..."
        Invoke-CompileCheck

        Write-Host "[verify] smoke tests..."
        Invoke-SmokeTests

        Write-Host "[verify] OK"
    }
    "verify-live" {
        Write-Host "[verify-live] context guard..."
        Invoke-ContextGuard

        Write-Host "[verify-live] compile check..."
        Invoke-CompileCheck

        Write-Host "[verify-live] smoke tests..."
        Invoke-SmokeTests

        Write-Host "[verify-live] production-order live API smoke..."
        Invoke-ProductionOrderApiSmoke

        Write-Host "[verify-live] OK"
    }
}
