param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("up", "ps", "logs", "test", "health", "proposal", "proposal-from-wb", "mvp-first-analytics", "mvp-live-readiness", "validate-mvp-summary", "validate-mvp-verification-manifest", "po-api-smoke", "po-api-smoke-positive", "po-api-smoke-host-positive", "context", "verify", "verify-host", "verify-live", "verify-mvp", "verify-mvp-reports")]
    [string]$Command,
    [ValidateRange(0, 2147483647)]
    [int]$ArticleId = 0,
    [ValidateRange(1, 1000)]
    [int]$ReadinessLimit = 100,
    [ValidateRange(0, 3650)]
    [int]$FreshnessSalesStaleAfterDays = 3,
    [ValidateRange(0, 3650)]
    [int]$FreshnessStockStaleAfterDays = 3,
    [string]$ReportPath = "",
    [string]$ManifestPath = ""
)

$ComposeFile = ".\\docker-compose.yml"
$MvpRequiredHostPorts = @(5432, 8000)

function Get-ContextBaseRef {
    $BaseRef = git merge-base HEAD origin/main 2>$null
    if (-not $BaseRef) {
        return "HEAD~1"
    }

    return $BaseRef.Trim()
}

function Invoke-ContextGuard {
    $BaseRef = Get-ContextBaseRef
    python .\scripts\context_guard.py --base $BaseRef --head HEAD --include-working-tree
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

function Invoke-MvpSummarySchemaValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReportPath,
        [string]$LogPrefix = "validate-mvp-summary"
    )

    if (-not $ReportPath) {
        throw "[$LogPrefix] FAIL summary schema validation: report path is required."
    }

    $ValidationOutput = python -m scripts.validate_mvp_report_summary_schema $ReportPath 2>&1
    $ValidationExitCode = $LASTEXITCODE
    if ($ValidationOutput) {
        $ValidationOutput | ForEach-Object { Write-Host "[$LogPrefix] $_" }
    }
    if ($ValidationExitCode -ne 0) {
        throw "[$LogPrefix] FAIL summary schema validation."
    }
}

function Invoke-MvpVerificationManifestValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath,
        [string]$LogPrefix = "validate-mvp-verification-manifest"
    )

    if (-not $ManifestPath) {
        throw "[$LogPrefix] FAIL verification manifest validation: manifest path is required."
    }

    $ValidationOutput = python -m scripts.validate_mvp_report_verification_manifest $ManifestPath 2>&1
    $ValidationExitCode = $LASTEXITCODE
    if ($ValidationOutput) {
        $ValidationOutput | ForEach-Object { Write-Host "[$LogPrefix] $_" }
    }
    if ($ValidationExitCode -ne 0) {
        throw "[$LogPrefix] FAIL verification manifest validation."
    }
}

function Get-LatestArtifactDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath
    )

    $Directory = Get-ChildItem -Path $RootPath -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $Directory) {
        throw "latest artifact directory not found under: $RootPath"
    }
    return $Directory.FullName
}

function Get-DockerAvailabilityMode {
    $DockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $DockerCommand) {
        return "missing-cli"
    }

    docker version --format "{{.Server.Version}}" 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        return "ready"
    }

    return "daemon-unreachable"
}

function Assert-DockerAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $DockerAvailabilityMode = Get-DockerAvailabilityMode
    if ($DockerAvailabilityMode -eq "ready") {
        return
    }

    if ($DockerAvailabilityMode -eq "missing-cli") {
        Write-Host "[$CommandName] docker CLI is not installed or not available in PATH." -ForegroundColor Yellow
        Write-Host "[$CommandName] Install Docker Desktop (or add docker to PATH) and retry." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "[$CommandName] Docker daemon is not reachable. Start Docker Desktop and wait until the engine is running, then retry." -ForegroundColor Yellow
    exit 1
}

function Assert-MvpHostPortsAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName,
        [int[]]$Ports = $MvpRequiredHostPorts
    )

    try {
        $ListeningPorts = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
            ForEach-Object { $_.Port } |
            Sort-Object -Unique
    }
    catch {
        Write-Host "[$CommandName] unable to inspect host TCP listeners; continuing without port preflight." -ForegroundColor Yellow
        return
    }

    $BusyPorts = @($Ports | Where-Object { $ListeningPorts -contains $_ })
    if ($BusyPorts.Count -eq 0) {
        return
    }

    $BusyPortsText = ($BusyPorts | Sort-Object | ForEach-Object { "$_" }) -join ", "
    Write-Host "[$CommandName] required host port(s) already in use: $BusyPortsText" -ForegroundColor Yellow
    Write-Host "[$CommandName] Stop the process using these ports or change the compose port mapping, then retry." -ForegroundColor Yellow
    exit 1
}

function Assert-DockerComposeConfigValid {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $ComposeValidationOutput = & docker compose -f $ComposeFile config 2>&1
    $ComposeValidationExitCode = $LASTEXITCODE
    if ($ComposeValidationExitCode -eq 0) {
        return
    }

    if ($ComposeValidationOutput) {
        $ComposeValidationOutput | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    }

    Write-Host "[$CommandName] docker compose config validation failed. Fix docker-compose.yml or env interpolation and retry." -ForegroundColor Yellow
    exit 1
}

function Invoke-DockerComposeBackendBuild {
    Assert-DockerAvailable -CommandName "po-api-smoke"
    $RunningServices = docker compose -f $ComposeFile ps --status running --services 2>$null
    $RunningServiceNames = @()
    if ($LASTEXITCODE -eq 0) {
        $RunningServiceNames = @($RunningServices | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    if ($RunningServiceNames.Count -eq 0) {
        Assert-MvpHostPortsAvailable -CommandName "po-api-smoke"
    }
    Assert-DockerComposeConfigValid -CommandName "po-api-smoke"

    $ComposeArgs = @("compose", "-f", $ComposeFile, "up", "-d", "--build", "backend")

    $BuildOutput = & docker @ComposeArgs 2>&1
    $BuildExitCode = $LASTEXITCODE
    if ($BuildOutput) {
        $BuildOutput | ForEach-Object { Write-Host $_ }
    }

    if ($BuildExitCode -eq 0) {
        return
    }

    $BuildOutputText = ($BuildOutput | Out-String)
    $ShouldRetryWithLegacyBuilder = (
        ($BuildOutputText -match "failed to fetch anonymous token") -or
        ($BuildOutputText -match "auth\.docker\.io/token") -or
        ($BuildOutputText -match "failed to solve")
    )

    if (-not $ShouldRetryWithLegacyBuilder) {
        exit $BuildExitCode
    }

    Write-Host "[po-api-smoke] detected transient Docker Hub auth/buildkit issue, retrying with DOCKER_BUILDKIT=0..." -ForegroundColor Yellow

    $PreviousDockerBuildkit = $env:DOCKER_BUILDKIT
    try {
        $env:DOCKER_BUILDKIT = "0"
        $RetryOutput = & docker @ComposeArgs 2>&1
        $RetryExitCode = $LASTEXITCODE
        if ($RetryOutput) {
            $RetryOutput | ForEach-Object { Write-Host $_ }
        }

        if ($RetryExitCode -ne 0) {
            exit $RetryExitCode
        }
    }
    finally {
        if ($null -eq $PreviousDockerBuildkit) {
            Remove-Item Env:DOCKER_BUILDKIT -ErrorAction SilentlyContinue
        }
        else {
            $env:DOCKER_BUILDKIT = $PreviousDockerBuildkit
        }
    }
}

function Wait-BackendRunning {
    param(
        [int]$TimeoutSeconds = 30
    )

    Assert-DockerAvailable -CommandName "backend-status"

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

function Write-DockerBackendDiagnostics {
    param(
        [string]$CommandName = "po-api-smoke",
        [int]$LogTail = 120
    )

    Write-Host "[$CommandName] docker compose ps:" -ForegroundColor Yellow
    docker compose -f $ComposeFile ps

    Write-Host "[$CommandName] db logs (tail=$LogTail):" -ForegroundColor Yellow
    docker compose -f $ComposeFile logs --tail=$LogTail db

    Write-Host "[$CommandName] backend logs (tail=$LogTail):" -ForegroundColor Yellow
    docker compose -f $ComposeFile logs --tail=$LogTail backend
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

function Invoke-ApiExpectedStatusOrThrow {
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
        [string]$ExpectedBodyContains = "",
        [string]$LogPrefix = "po-api-smoke-host"
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
            if (Test-Path $ResponseFile) {
                $ResponseBody = Get-Content -Raw $ResponseFile
                if ($ResponseBody) {
                    $ResponseBody | Write-Host
                }
            }
            throw "[$LogPrefix] FAIL ${Name}: curl exited with code $LASTEXITCODE"
        }

        if (Test-Path $ResponseFile) {
            $ResponseBody = Get-Content -Raw $ResponseFile
        }

        if ("$StatusCode" -ne "$ExpectedStatus") {
            if ($ResponseBody) {
                $ResponseBody | Write-Host
            }
            throw "[$LogPrefix] FAIL ${Name}: expected HTTP $ExpectedStatus, got HTTP $StatusCode"
        }

        if ($ExpectedBodyContains -and -not $ResponseBody.Contains($ExpectedBodyContains)) {
            if ($ResponseBody) {
                $ResponseBody | Write-Host
            }
            throw "[$LogPrefix] FAIL ${Name}: response body does not include expected fragment '$ExpectedBodyContains'"
        }

        Write-Host "[$LogPrefix] OK  $Name -> HTTP $StatusCode"
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

function Invoke-ApiAndWriteResponseOrThrow {
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
        [string]$LogPrefix = "proposal"
    )

    $ResponseFile = [System.IO.Path]::GetTempFileName()
    $HeaderFile = [System.IO.Path]::GetTempFileName()
    $PayloadFile = $null
    $ResponseBody = ""
    $ResponseHeaders = ""
    try {
        if ($JsonBody) {
            $PayloadFile = [System.IO.Path]::GetTempFileName()
            $JsonBody | Set-Content -Encoding utf8 -NoNewline $PayloadFile
            $StatusCode = curl.exe -sS -o $ResponseFile -D $HeaderFile -w "%{http_code}" -X $Method $Url -H "Content-Type: application/json" --data-binary "@$PayloadFile"
        }
        else {
            $StatusCode = curl.exe -sS -o $ResponseFile -D $HeaderFile -w "%{http_code}" -X $Method $Url
        }

        if ($LASTEXITCODE -ne 0) {
            if (Test-Path $ResponseFile) {
                $ResponseBody = Get-Content -Raw $ResponseFile
                if ($ResponseBody) {
                    $ResponseBody | Write-Host
                }
            }
            throw "[$LogPrefix] FAIL ${Name}: curl exited with code $LASTEXITCODE"
        }

        if (Test-Path $HeaderFile) {
            $ResponseHeaders = Get-Content -Raw $HeaderFile
        }

        if (Test-Path $ResponseFile) {
            $ResponseBody = Get-Content -Raw $ResponseFile
            if ($ResponseBody) {
                try {
                    $ResponseBody = ($ResponseBody | ConvertFrom-Json | ConvertTo-Json -Depth 100)
                }
                catch {
                }
            }
        }

        if ("$StatusCode" -ne "$ExpectedStatus") {
            if ($ResponseHeaders) {
                $ResponseHeaders | Write-Host
            }
            if ($ResponseBody) {
                $ResponseBody | Write-Host
            }
            throw "[$LogPrefix] FAIL ${Name}: expected HTTP $ExpectedStatus, got HTTP $StatusCode"
        }

        if ($ResponseHeaders) {
            $ResponseHeaders | Write-Host
        }
        if ($ResponseBody) {
            $ResponseBody | Write-Host
        }

        Write-Host "[$LogPrefix] OK  $Name -> HTTP $StatusCode"
    }
    finally {
        if ($PayloadFile -and (Test-Path $PayloadFile)) {
            Remove-Item $PayloadFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $HeaderFile) {
            Remove-Item $HeaderFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $ResponseFile) {
            Remove-Item $ResponseFile -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-ApiAndSaveResponseOrThrow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [int]$ExpectedStatus,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath,
        [string]$JsonBody = "",
        [string]$LogPrefix = "mvp-first-analytics"
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
            throw "[$LogPrefix] FAIL ${Name}: curl exited with code $LASTEXITCODE"
        }

        if (Test-Path $ResponseFile) {
            $ResponseBody = Get-Content -Raw $ResponseFile
        }

        if ("$StatusCode" -ne "$ExpectedStatus") {
            if ($ResponseBody) {
                $ResponseBody | Write-Host
            }
            throw "[$LogPrefix] FAIL ${Name}: expected HTTP $ExpectedStatus, got HTTP $StatusCode"
        }

        $OutputParent = Split-Path -Parent $OutputPath
        if ($OutputParent -and -not (Test-Path $OutputParent)) {
            New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
        }

        try {
            $ResponseBody = ($ResponseBody | ConvertFrom-Json | ConvertTo-Json -Depth 100)
        }
        catch {
        }
        $ResponseBody | Set-Content -Encoding utf8 -NoNewline $OutputPath

        Write-Host "[$LogPrefix] OK  $Name -> HTTP $StatusCode -> $OutputPath"
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
        Invoke-DockerComposeBackendBuild

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

function Invoke-ProductionOrderApiSmokePositive {
    Write-Host "[po-api-smoke] syncing backend image with current workspace..."
    Invoke-DockerComposeBackendBuild

    try {
        if (-not (Wait-BackendRunning -TimeoutSeconds 45)) {
            throw "[po-api-smoke] backend did not reach running state in time."
        }

        if (-not (Wait-ApiHealthy -TimeoutSeconds 45)) {
            throw "[po-api-smoke] health endpoint did not become ready in time."
        }

        Invoke-ApiExpectedStatusOrThrow -Name "planning-core-health" -Method "GET" -Url "http://localhost:8000/api/v1/planning/core/health" -ExpectedStatus 200 -LogPrefix "po-api-smoke"

        $SeedOutput = docker compose -f $ComposeFile exec -T backend python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[po-api-smoke] FAIL seed step: unable to prepare smoke dataset."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[po-api-smoke] FAIL seed step: invalid seed JSON output."
        }

        $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
        $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress
        $PurchaseOrderFromProposalHappyPayload = $SeedData.purchase_order_from_proposal_payload | ConvertTo-Json -Depth 8 -Compress
        $ShipmentComparisonPayload = $SeedData.shipment_comparison_payload | ConvertTo-Json -Depth 8 -Compress

        Invoke-ApiExpectedStatusOrThrow -Name "production-order-direct-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 200 -JsonBody $DirectHappyPayload -ExpectedBodyContains '"status":"ok"' -LogPrefix "po-api-smoke"
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-from-wb-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -ExpectedBodyContains '"status":"ok"' -LogPrefix "po-api-smoke"
        Invoke-ApiExpectedStatusOrThrow -Name "purchase-order-from-proposal-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/purchase-order/from-proposal" -ExpectedStatus 201 -JsonBody $PurchaseOrderFromProposalHappyPayload -ExpectedBodyContains '"status":"draft"' -LogPrefix "po-api-smoke"
        Invoke-ApiExpectedStatusOrThrow -Name "shipment-comparison-happy-path" -Method "POST" -Url "http://localhost:8000/api/v1/wb/manager/shipment/from-proposal/comparison" -ExpectedStatus 200 -JsonBody $ShipmentComparisonPayload -ExpectedBodyContains '"divergence_summary"' -LogPrefix "po-api-smoke"

        return $SeedData
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        Write-DockerBackendDiagnostics -CommandName "po-api-smoke"
        exit 1
    }
}

function Invoke-ProductionOrderApiSmoke {
    Invoke-ProductionOrderApiSmokePositive | Out-Null

    try {
        $UnknownArticleDirectPayload = '{"article_id":999999999,"planning_horizon_days":90,"bundle_daily_sales":[{"bundle_type_id":1,"daily_sales":1.0}],"bundle_stock":[{"bundle_type_id":1,"wb_qty":0,"local_qty":0}],"in_flight_supply":[],"size_weights":{}}'
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-direct-unknown-article" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 404 -JsonBody $UnknownArticleDirectPayload -ExpectedBodyContains 'Article not found' -LogPrefix "po-api-smoke"

        $UnknownArticleFromWbPayload = '{"article_id":999999999,"planning_horizon_days":90,"observation_window_days":30,"bundle_type_ids":[1],"in_flight_supply":[],"size_weights":{}}'
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-from-wb-unknown-article" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 404 -JsonBody $UnknownArticleFromWbPayload -ExpectedBodyContains 'Article not found' -LogPrefix "po-api-smoke"

        $UnknownArticlePurchaseOrderPayload = '{"article_id":999999999,"target_date":"2030-01-31","comment":"Missing article smoke","explanation":true}'
        Invoke-ApiExpectedStatusOrThrow -Name "purchase-order-from-proposal-unknown-article" -Method "POST" -Url "http://localhost:8000/api/v1/purchase-order/from-proposal" -ExpectedStatus 404 -JsonBody $UnknownArticlePurchaseOrderPayload -ExpectedBodyContains 'article_not_found' -LogPrefix "po-api-smoke"

        $DirectInvalidPayload = '{"article_id":1,"planning_horizon_days":0,"bundle_daily_sales":[]}'
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-direct-validation" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 422 -JsonBody $DirectInvalidPayload -ExpectedBodyContains 'planning_horizon_days' -LogPrefix "po-api-smoke"

        $FromWbInvalidPayload = '{"article_id":1,"planning_horizon_days":90,"observation_window_days":30,"freshness_mode":"hard_fail","bundle_type_ids":[1],"in_flight_supply":[],"size_weights":{}}'
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-from-wb-validation" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 422 -JsonBody $FromWbInvalidPayload -ExpectedBodyContains 'freshness_mode' -LogPrefix "po-api-smoke"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        Write-DockerBackendDiagnostics -CommandName "po-api-smoke"
        exit 1
    }
}

function Invoke-LiveProductionOrderProposal {
    try {
        $SeedOutput = docker compose -f $ComposeFile exec -T backend python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[proposal] FAIL seed step: unable to prepare canonical production-order payload."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[proposal] FAIL seed step: invalid seed JSON output."
        }

        $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
        Invoke-ApiAndWriteResponseOrThrow -Name "production-order-direct-proposal" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal" -ExpectedStatus 200 -JsonBody $DirectHappyPayload -LogPrefix "proposal"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        Write-DockerBackendDiagnostics -CommandName "proposal"
        exit 1
    }
}

function Invoke-LiveProductionOrderProposalFromWb {
    try {
        $SeedOutput = docker compose -f $ComposeFile exec -T backend python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[proposal-from-wb] FAIL seed step: unable to prepare canonical production-order payload."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[proposal-from-wb] FAIL seed step: invalid seed JSON output."
        }

        $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress
        Invoke-ApiAndWriteResponseOrThrow -Name "production-order-from-wb-proposal" -Method "POST" -Url "http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb" -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -LogPrefix "proposal-from-wb"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        Write-DockerBackendDiagnostics -CommandName "proposal-from-wb"
        exit 1
    }
}

function Invoke-HostProductionOrderApiSmokePositive {
    $BaseUrl = "http://127.0.0.1:8010"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $DirectUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal"
    $FromWbUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal/from-wb"
    $ShipmentComparisonUrl = "$BaseUrl/api/v1/wb/manager/shipment/from-proposal/comparison"
    $PreviousDatabaseUrl = $env:DATABASE_URL
    $PreviousSchedulerEnabled = $env:MONITORING_SCHEDULER_ENABLED
    $StdOutFile = [System.IO.Path]::GetTempFileName()
    $StdErrFile = [System.IO.Path]::GetTempFileName()
    $ServerProcess = $null

    try {
        $env:DATABASE_URL = "sqlite:///./ci.db"
        $env:MONITORING_SCHEDULER_ENABLED = "false"

        Write-Host "[po-api-smoke-host] bootstrapping SQLite schema..."
        python -c "from app.models.base import Base; import app.models.models; from app.core.db import engine; Base.metadata.create_all(bind=engine)"
        if ($LASTEXITCODE -ne 0) {
            throw "[po-api-smoke-host] FAIL schema bootstrap step."
        }

        Write-Host "[po-api-smoke-host] starting host uvicorn..."
        $ServerProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory (Get-Location).Path -PassThru -RedirectStandardOutput $StdOutFile -RedirectStandardError $StdErrFile -ErrorAction Stop

        if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 45)) {
            Write-Host "[po-api-smoke-host] health endpoint did not become ready in time." -ForegroundColor Yellow
            if (Test-Path $StdOutFile) {
                Get-Content -Raw $StdOutFile | Write-Host
            }
            if (Test-Path $StdErrFile) {
                Get-Content -Raw $StdErrFile | Write-Host
            }
            throw "[po-api-smoke-host] FAIL host health readiness."
        }

        Invoke-ApiExpectedStatusOrThrow -Name "planning-core-health" -Method "GET" -Url $HealthUrl -ExpectedStatus 200 -LogPrefix "po-api-smoke-host"

        $SeedOutput = python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            throw "[po-api-smoke-host] FAIL seed step: unable to prepare smoke dataset."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[po-api-smoke-host] FAIL seed step: invalid seed JSON output."
        }

        $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
        $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress
        $ShipmentComparisonPayload = $SeedData.shipment_comparison_payload | ConvertTo-Json -Depth 8 -Compress

        Invoke-ApiExpectedStatusOrThrow -Name "production-order-direct-happy-path" -Method "POST" -Url $DirectUrl -ExpectedStatus 200 -JsonBody $DirectHappyPayload -ExpectedBodyContains '"status":"ok"' -LogPrefix "po-api-smoke-host"
        Invoke-ApiExpectedStatusOrThrow -Name "production-order-from-wb-happy-path" -Method "POST" -Url $FromWbUrl -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -ExpectedBodyContains '"status":"ok"' -LogPrefix "po-api-smoke-host"
        Invoke-ApiExpectedStatusOrThrow -Name "shipment-comparison-happy-path" -Method "POST" -Url $ShipmentComparisonUrl -ExpectedStatus 200 -JsonBody $ShipmentComparisonPayload -ExpectedBodyContains '"divergence_summary"' -LogPrefix "po-api-smoke-host"

        return $SeedData
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
    finally {
        if ($null -ne $ServerProcess) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdOutFile) {
            Remove-Item $StdOutFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdErrFile) {
            Remove-Item $StdErrFile -ErrorAction SilentlyContinue
        }
        if ($null -eq $PreviousDatabaseUrl) {
            Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DATABASE_URL = $PreviousDatabaseUrl
        }
        if ($null -eq $PreviousSchedulerEnabled) {
            Remove-Item Env:MONITORING_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:MONITORING_SCHEDULER_ENABLED = $PreviousSchedulerEnabled
        }
    }
}

function Invoke-HostProductionOrderProposal {
    $BaseUrl = "http://127.0.0.1:8010"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $DirectUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal"
    $PreviousDatabaseUrl = $env:DATABASE_URL
    $PreviousSchedulerEnabled = $env:MONITORING_SCHEDULER_ENABLED
    $StdOutFile = [System.IO.Path]::GetTempFileName()
    $StdErrFile = [System.IO.Path]::GetTempFileName()
    $ServerProcess = $null

    try {
        $env:DATABASE_URL = "sqlite:///./ci.db"
        $env:MONITORING_SCHEDULER_ENABLED = "false"

        Write-Host "[proposal-host] bootstrapping SQLite schema..."
        python -c "from app.models.base import Base; import app.models.models; from app.core.db import engine; Base.metadata.create_all(bind=engine)"
        if ($LASTEXITCODE -ne 0) {
            throw "[proposal-host] FAIL schema bootstrap step."
        }

        Write-Host "[proposal-host] starting host uvicorn..."
        $ServerProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory (Get-Location).Path -PassThru -RedirectStandardOutput $StdOutFile -RedirectStandardError $StdErrFile -ErrorAction Stop

        if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 45)) {
            Write-Host "[proposal-host] health endpoint did not become ready in time." -ForegroundColor Yellow
            if (Test-Path $StdOutFile) {
                Get-Content -Raw $StdOutFile | Write-Host
            }
            if (Test-Path $StdErrFile) {
                Get-Content -Raw $StdErrFile | Write-Host
            }
            throw "[proposal-host] FAIL host health readiness."
        }

        $SeedOutput = python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[proposal-host] FAIL seed step: unable to prepare canonical production-order payload."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[proposal-host] FAIL seed step: invalid seed JSON output."
        }

        $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
        Invoke-ApiAndWriteResponseOrThrow -Name "production-order-direct-proposal" -Method "POST" -Url $DirectUrl -ExpectedStatus 200 -JsonBody $DirectHappyPayload -LogPrefix "proposal-host"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        if (Test-Path $StdOutFile) {
            $StdOut = Get-Content -Raw $StdOutFile
            if ($StdOut) {
                $StdOut | Write-Host
            }
        }
        if (Test-Path $StdErrFile) {
            $StdErr = Get-Content -Raw $StdErrFile
            if ($StdErr) {
                $StdErr | Write-Host
            }
        }
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
    finally {
        if ($null -ne $ServerProcess) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdOutFile) {
            Remove-Item $StdOutFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdErrFile) {
            Remove-Item $StdErrFile -ErrorAction SilentlyContinue
        }
        if ($null -eq $PreviousDatabaseUrl) {
            Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DATABASE_URL = $PreviousDatabaseUrl
        }
        if ($null -eq $PreviousSchedulerEnabled) {
            Remove-Item Env:MONITORING_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:MONITORING_SCHEDULER_ENABLED = $PreviousSchedulerEnabled
        }
    }
}

function Invoke-HostProductionOrderProposalFromWb {
    $BaseUrl = "http://127.0.0.1:8010"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $FromWbUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal/from-wb"
    $PreviousDatabaseUrl = $env:DATABASE_URL
    $PreviousSchedulerEnabled = $env:MONITORING_SCHEDULER_ENABLED
    $StdOutFile = [System.IO.Path]::GetTempFileName()
    $StdErrFile = [System.IO.Path]::GetTempFileName()
    $ServerProcess = $null

    try {
        $env:DATABASE_URL = "sqlite:///./ci.db"
        $env:MONITORING_SCHEDULER_ENABLED = "false"

        Write-Host "[proposal-from-wb-host] bootstrapping SQLite schema..."
        python -c "from app.models.base import Base; import app.models.models; from app.core.db import engine; Base.metadata.create_all(bind=engine)"
        if ($LASTEXITCODE -ne 0) {
            throw "[proposal-from-wb-host] FAIL schema bootstrap step."
        }

        Write-Host "[proposal-from-wb-host] starting host uvicorn..."
        $ServerProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory (Get-Location).Path -PassThru -RedirectStandardOutput $StdOutFile -RedirectStandardError $StdErrFile -ErrorAction Stop

        if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 45)) {
            Write-Host "[proposal-from-wb-host] health endpoint did not become ready in time." -ForegroundColor Yellow
            if (Test-Path $StdOutFile) {
                Get-Content -Raw $StdOutFile | Write-Host
            }
            if (Test-Path $StdErrFile) {
                Get-Content -Raw $StdErrFile | Write-Host
            }
            throw "[proposal-from-wb-host] FAIL host health readiness."
        }

        $SeedOutput = python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[proposal-from-wb-host] FAIL seed step: unable to prepare canonical production-order payload."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[proposal-from-wb-host] FAIL seed step: invalid seed JSON output."
        }

        $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress
        Invoke-ApiAndWriteResponseOrThrow -Name "production-order-from-wb-proposal" -Method "POST" -Url $FromWbUrl -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -LogPrefix "proposal-from-wb-host"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        if (Test-Path $StdOutFile) {
            $StdOut = Get-Content -Raw $StdOutFile
            if ($StdOut) {
                $StdOut | Write-Host
            }
        }
        if (Test-Path $StdErrFile) {
            $StdErr = Get-Content -Raw $StdErrFile
            if ($StdErr) {
                $StdErr | Write-Host
            }
        }
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
    finally {
        if ($null -ne $ServerProcess) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdOutFile) {
            Remove-Item $StdOutFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdErrFile) {
            Remove-Item $StdErrFile -ErrorAction SilentlyContinue
        }
        if ($null -eq $PreviousDatabaseUrl) {
            Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DATABASE_URL = $PreviousDatabaseUrl
        }
        if ($null -eq $PreviousSchedulerEnabled) {
            Remove-Item Env:MONITORING_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:MONITORING_SCHEDULER_ENABLED = $PreviousSchedulerEnabled
        }
    }
}

function Invoke-HostMvpFirstAnalyticsReport {
    $BaseUrl = "http://127.0.0.1:8010"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $DirectUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal"
    $FromWbUrl = "$BaseUrl/api/v1/planning/core/production-order/proposal/from-wb"
    $ShipmentComparisonUrl = "$BaseUrl/api/v1/wb/manager/shipment/from-proposal/comparison"
    $MonitoringDashboardUrl = "$BaseUrl/api/v1/planning/monitoring/dashboard"
    $MonitoringRiskFocusUrl = "$BaseUrl/api/v1/planning/monitoring/risk-focus"
    $MonitoringTimeseriesUrl = "$BaseUrl/api/v1/planning/monitoring/timeseries?metrics=risk_critical&metrics=risk_warning&metrics=total_final_order_qty"
    $PreviousDatabaseUrl = $env:DATABASE_URL
    $PreviousSchedulerEnabled = $env:MONITORING_SCHEDULER_ENABLED
    $StdOutFile = [System.IO.Path]::GetTempFileName()
    $StdErrFile = [System.IO.Path]::GetTempFileName()
    $ServerProcess = $null
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path (Get-Location).Path "artifacts\mvp_first_analytics\$Timestamp"

    try {
        $env:DATABASE_URL = "sqlite:///./ci.db"
        $env:MONITORING_SCHEDULER_ENABLED = "false"

        Write-Host "[mvp-first-analytics] bootstrapping SQLite schema..."
        python -c "from app.models.base import Base; import app.models.models; from app.core.db import engine; Base.metadata.create_all(bind=engine)"
        if ($LASTEXITCODE -ne 0) {
            throw "[mvp-first-analytics] FAIL schema bootstrap step."
        }

        Write-Host "[mvp-first-analytics] starting host uvicorn..."
        $ServerProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory (Get-Location).Path -PassThru -RedirectStandardOutput $StdOutFile -RedirectStandardError $StdErrFile -ErrorAction Stop

        if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 45)) {
            Write-Host "[mvp-first-analytics] health endpoint did not become ready in time." -ForegroundColor Yellow
            if (Test-Path $StdOutFile) {
                Get-Content -Raw $StdOutFile | Write-Host
            }
            if (Test-Path $StdErrFile) {
                Get-Content -Raw $StdErrFile | Write-Host
            }
            throw "[mvp-first-analytics] FAIL host health readiness."
        }

        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

        $SeedOutput = python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[mvp-first-analytics] FAIL seed step: unable to prepare smoke dataset."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[mvp-first-analytics] FAIL seed step: invalid seed JSON output."
        }

        ($SeedData | ConvertTo-Json -Depth 100) | Set-Content -Encoding utf8 -NoNewline (Join-Path $OutputDir "seed_payloads.json")

        $DirectHappyPayload = $SeedData.direct_payload | ConvertTo-Json -Depth 8 -Compress
        $FromWbHappyPayload = $SeedData.from_wb_payload | ConvertTo-Json -Depth 8 -Compress
        $ShipmentComparisonPayload = $SeedData.shipment_comparison_payload | ConvertTo-Json -Depth 8 -Compress
        $RequestMetadata = [ordered]@{
            generated_at = (Get-Date).ToString("o")
            base_url = $BaseUrl
            requests = @(
                [ordered]@{ name = "planning-core-health"; method = "GET"; url = $HealthUrl; body = $null },
                [ordered]@{ name = "production-order-direct"; method = "POST"; url = $DirectUrl; body = $SeedData.direct_payload },
                [ordered]@{ name = "production-order-from-wb"; method = "POST"; url = $FromWbUrl; body = $SeedData.from_wb_payload },
                [ordered]@{ name = "shipment-comparison"; method = "POST"; url = $ShipmentComparisonUrl; body = $SeedData.shipment_comparison_payload },
                [ordered]@{ name = "monitoring-dashboard"; method = "GET"; url = $MonitoringDashboardUrl; body = $null },
                [ordered]@{ name = "monitoring-risk-focus"; method = "GET"; url = $MonitoringRiskFocusUrl; body = $null },
                [ordered]@{ name = "monitoring-timeseries"; method = "GET"; url = $MonitoringTimeseriesUrl; body = $null }
            )
        }
        ($RequestMetadata | ConvertTo-Json -Depth 100) | Set-Content -Encoding utf8 -NoNewline (Join-Path $OutputDir "requests.json")

        Invoke-ApiAndSaveResponseOrThrow -Name "planning-core-health" -Method "GET" -Url $HealthUrl -ExpectedStatus 200 -OutputPath (Join-Path $OutputDir "planning_core_health.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "production-order-direct" -Method "POST" -Url $DirectUrl -ExpectedStatus 200 -JsonBody $DirectHappyPayload -OutputPath (Join-Path $OutputDir "production_order_direct.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "production-order-from-wb" -Method "POST" -Url $FromWbUrl -ExpectedStatus 200 -JsonBody $FromWbHappyPayload -OutputPath (Join-Path $OutputDir "production_order_from_wb.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "shipment-comparison" -Method "POST" -Url $ShipmentComparisonUrl -ExpectedStatus 200 -JsonBody $ShipmentComparisonPayload -OutputPath (Join-Path $OutputDir "shipment_comparison.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "monitoring-dashboard" -Method "GET" -Url $MonitoringDashboardUrl -ExpectedStatus 200 -OutputPath (Join-Path $OutputDir "monitoring_dashboard.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "monitoring-risk-focus" -Method "GET" -Url $MonitoringRiskFocusUrl -ExpectedStatus 200 -OutputPath (Join-Path $OutputDir "monitoring_risk_focus.json")
        Invoke-ApiAndSaveResponseOrThrow -Name "monitoring-timeseries" -Method "GET" -Url $MonitoringTimeseriesUrl -ExpectedStatus 200 -OutputPath (Join-Path $OutputDir "monitoring_timeseries.json")

        $SummaryPath = python -m scripts.mvp_first_analytics_summary $OutputDir
        if ($LASTEXITCODE -ne 0) {
            throw "[mvp-first-analytics] FAIL summary step."
        }

        Invoke-MvpSummarySchemaValidation -ReportPath $OutputDir -LogPrefix "mvp-first-analytics"

        Write-Host "[mvp-first-analytics] OK"
        Write-Host "[mvp-first-analytics] report directory: $OutputDir"
        Write-Host "[mvp-first-analytics] summary: $SummaryPath"
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
    finally {
        if ($null -ne $ServerProcess) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdOutFile) {
            Remove-Item $StdOutFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdErrFile) {
            Remove-Item $StdErrFile -ErrorAction SilentlyContinue
        }
        if ($null -eq $PreviousDatabaseUrl) {
            Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DATABASE_URL = $PreviousDatabaseUrl
        }
        if ($null -eq $PreviousSchedulerEnabled) {
            Remove-Item Env:MONITORING_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:MONITORING_SCHEDULER_ENABLED = $PreviousSchedulerEnabled
        }
    }
}

function Invoke-MvpLiveReadinessReport {
    $BaseUrl = "http://localhost:8000"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $ReadinessUrl = "$BaseUrl/api/v1/wb/from-wb/readiness"
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path (Get-Location).Path "artifacts\mvp_live_readiness\$Timestamp"
    $PayloadObject = [ordered]@{
        limit = $ReadinessLimit
        freshness_sales_stale_after_days = $FreshnessSalesStaleAfterDays
        freshness_stock_stale_after_days = $FreshnessStockStaleAfterDays
    }
    if ($ArticleId -gt 0) {
        $PayloadObject.article_id = $ArticleId
    }
    $Payload = $PayloadObject | ConvertTo-Json -Compress

    if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 10)) {
        Write-Host "[mvp-live-readiness] backend is not reachable at $BaseUrl." -ForegroundColor Yellow
        Write-Host "[mvp-live-readiness] Start the backend first with '.\scripts\dev.ps1 up' or your usual uvicorn command, then rerun." -ForegroundColor Yellow
        exit 1
    }

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    Set-Content -Path (Join-Path $OutputDir "request.json") -Value $Payload -Encoding UTF8

    Invoke-ApiAndSaveResponseOrThrow -Name "from-wb-readiness" -Method "POST" -Url $ReadinessUrl -ExpectedStatus 200 -JsonBody $Payload -OutputPath (Join-Path $OutputDir "readiness.json") -LogPrefix "mvp-live-readiness"

    $SummaryOutput = python -m scripts.mvp_live_readiness_summary $OutputDir
    if ($LASTEXITCODE -ne 0) {
        throw "[mvp-live-readiness] FAIL summary step."
    }

    Invoke-MvpSummarySchemaValidation -ReportPath $OutputDir -LogPrefix "mvp-live-readiness"

    Write-Host "[mvp-live-readiness] OK"
    Write-Host "[mvp-live-readiness] report directory: $OutputDir"
    if ($SummaryOutput) {
        $SummaryOutput | ForEach-Object { Write-Host "[mvp-live-readiness] summary: $_" }
    }
}

function Invoke-HostMvpLiveReadinessReport {
    $BaseUrl = "http://127.0.0.1:8010"
    $HealthUrl = "$BaseUrl/api/v1/planning/core/health"
    $ReadinessUrl = "$BaseUrl/api/v1/wb/from-wb/readiness"
    $PreviousDatabaseUrl = $env:DATABASE_URL
    $PreviousSchedulerEnabled = $env:MONITORING_SCHEDULER_ENABLED
    $StdOutFile = [System.IO.Path]::GetTempFileName()
    $StdErrFile = [System.IO.Path]::GetTempFileName()
    $ServerProcess = $null
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path (Get-Location).Path "artifacts\mvp_live_readiness\$Timestamp"

    try {
        $env:DATABASE_URL = "sqlite:///./ci.db"
        $env:MONITORING_SCHEDULER_ENABLED = "false"

        Write-Host "[mvp-live-readiness-host] bootstrapping SQLite schema..."
        python -c "from app.models.base import Base; import app.models.models; from app.core.db import engine; Base.metadata.create_all(bind=engine)"
        if ($LASTEXITCODE -ne 0) {
            throw "[mvp-live-readiness-host] FAIL schema bootstrap step."
        }

        Write-Host "[mvp-live-readiness-host] starting host uvicorn..."
        $ServerProcess = Start-Process -FilePath "python" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory (Get-Location).Path -PassThru -RedirectStandardOutput $StdOutFile -RedirectStandardError $StdErrFile -ErrorAction Stop

        if (-not (Wait-ApiHealthy -Url $HealthUrl -TimeoutSeconds 45)) {
            Write-Host "[mvp-live-readiness-host] health endpoint did not become ready in time." -ForegroundColor Yellow
            if (Test-Path $StdOutFile) {
                Get-Content -Raw $StdOutFile | Write-Host
            }
            if (Test-Path $StdErrFile) {
                Get-Content -Raw $StdErrFile | Write-Host
            }
            throw "[mvp-live-readiness-host] FAIL host health readiness."
        }

        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

        $SeedOutput = python -m scripts.po_api_smoke_seed
        if ($LASTEXITCODE -ne 0) {
            if ($SeedOutput) {
                $SeedOutput | Write-Host
            }
            throw "[mvp-live-readiness-host] FAIL seed step: unable to prepare smoke dataset."
        }

        try {
            $SeedData = $SeedOutput | ConvertFrom-Json
        }
        catch {
            Write-Host $SeedOutput
            throw "[mvp-live-readiness-host] FAIL seed step: invalid seed JSON output."
        }

        $PayloadObject = [ordered]@{
            limit = $ReadinessLimit
            freshness_sales_stale_after_days = $FreshnessSalesStaleAfterDays
            freshness_stock_stale_after_days = $FreshnessStockStaleAfterDays
        }
        $SeedArticleId = $null
        if ($SeedData -and $SeedData.direct_payload) {
            $SeedArticleId = $SeedData.direct_payload.article_id
        }
        if ($ArticleId -gt 0) {
            $PayloadObject.article_id = $ArticleId
        }
        elseif ($null -ne $SeedArticleId) {
            $PayloadObject.article_id = [int]($SeedArticleId)
        }
        $Payload = $PayloadObject | ConvertTo-Json -Compress

        Set-Content -Path (Join-Path $OutputDir "request.json") -Value $Payload -Encoding UTF8

        Invoke-ApiAndSaveResponseOrThrow -Name "from-wb-readiness" -Method "POST" -Url $ReadinessUrl -ExpectedStatus 200 -JsonBody $Payload -OutputPath (Join-Path $OutputDir "readiness.json") -LogPrefix "mvp-live-readiness-host"

        $SummaryOutput = python -m scripts.mvp_live_readiness_summary $OutputDir
        if ($LASTEXITCODE -ne 0) {
            throw "[mvp-live-readiness-host] FAIL summary step."
        }

        Invoke-MvpSummarySchemaValidation -ReportPath $OutputDir -LogPrefix "mvp-live-readiness-host"

        Write-Host "[mvp-live-readiness-host] OK"
        Write-Host "[mvp-live-readiness-host] report directory: $OutputDir"
        if ($SummaryOutput) {
            $SummaryOutput | ForEach-Object { Write-Host "[mvp-live-readiness-host] summary: $_" }
        }
    }
    catch {
        $Message = $_.Exception.Message
        if (-not $Message) {
            $Message = $_
        }
        if (Test-Path $StdOutFile) {
            $StdOut = Get-Content -Raw $StdOutFile
            if ($StdOut) {
                $StdOut | Write-Host
            }
        }
        if (Test-Path $StdErrFile) {
            $StdErr = Get-Content -Raw $StdErrFile
            if ($StdErr) {
                $StdErr | Write-Host
            }
        }
        Write-Host $Message -ForegroundColor Red
        exit 1
    }
    finally {
        if ($null -ne $ServerProcess) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdOutFile) {
            Remove-Item $StdOutFile -ErrorAction SilentlyContinue
        }
        if (Test-Path $StdErrFile) {
            Remove-Item $StdErrFile -ErrorAction SilentlyContinue
        }
        if ($null -eq $PreviousDatabaseUrl) {
            Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DATABASE_URL = $PreviousDatabaseUrl
        }
        if ($null -eq $PreviousSchedulerEnabled) {
            Remove-Item Env:MONITORING_SCHEDULER_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:MONITORING_SCHEDULER_ENABLED = $PreviousSchedulerEnabled
        }
    }
}

switch ($Command) {
    "up" {
        Assert-DockerAvailable -CommandName "up"
        Assert-MvpHostPortsAvailable -CommandName "up"
        Assert-DockerComposeConfigValid -CommandName "up"
        docker compose -f $ComposeFile up -d --build db backend
    }
    "ps" {
        Assert-DockerAvailable -CommandName "ps"
        docker compose -f $ComposeFile ps
    }
    "logs" {
        Assert-DockerAvailable -CommandName "logs"
        docker compose -f $ComposeFile logs --tail=200 backend
    }
    "test" {
        Assert-DockerAvailable -CommandName "test"
        docker compose -f $ComposeFile exec -T backend python -m pytest -q
    }
    "health" {
        curl.exe -i http://localhost:8000/api/v1/planning/core/health
    }
    "proposal" {
        $DockerAvailabilityMode = Get-DockerAvailabilityMode
        if ($DockerAvailabilityMode -eq "ready") {
            if ((Wait-BackendRunning -TimeoutSeconds 5) -and (Wait-ApiHealthy -TimeoutSeconds 5)) {
                Write-Host "[proposal] Docker backend reachable, using live canonical proposal..."
                Invoke-LiveProductionOrderProposal
                break
            }

            Write-Host "[proposal] Docker daemon reachable but backend is not ready, falling back to host canonical proposal..." -ForegroundColor Yellow
            Invoke-HostProductionOrderProposal
            break
        }

        if ($DockerAvailabilityMode -eq "missing-cli") {
            Write-Host "[proposal] docker CLI is not available, falling back to host canonical proposal..." -ForegroundColor Yellow
        }
        else {
            Write-Host "[proposal] Docker daemon is not reachable, falling back to host canonical proposal..." -ForegroundColor Yellow
        }

        Invoke-HostProductionOrderProposal
    }
    "proposal-from-wb" {
        $DockerAvailabilityMode = Get-DockerAvailabilityMode
        if ($DockerAvailabilityMode -eq "ready") {
            if ((Wait-BackendRunning -TimeoutSeconds 5) -and (Wait-ApiHealthy -TimeoutSeconds 5)) {
                Write-Host "[proposal-from-wb] Docker backend reachable, using live canonical proposal..."
                Invoke-LiveProductionOrderProposalFromWb
                break
            }

            Write-Host "[proposal-from-wb] Docker daemon reachable but backend is not ready, falling back to host canonical proposal..." -ForegroundColor Yellow
            Invoke-HostProductionOrderProposalFromWb
            break
        }

        if ($DockerAvailabilityMode -eq "missing-cli") {
            Write-Host "[proposal-from-wb] docker CLI is not available, falling back to host canonical proposal..." -ForegroundColor Yellow
        }
        else {
            Write-Host "[proposal-from-wb] Docker daemon is not reachable, falling back to host canonical proposal..." -ForegroundColor Yellow
        }

        Invoke-HostProductionOrderProposalFromWb
    }
    "mvp-first-analytics" {
        Invoke-HostMvpFirstAnalyticsReport
    }
    "mvp-live-readiness" {
        Invoke-MvpLiveReadinessReport
    }
    "validate-mvp-summary" {
        Invoke-MvpSummarySchemaValidation -ReportPath $ReportPath
    }
    "validate-mvp-verification-manifest" {
        Invoke-MvpVerificationManifestValidation -ManifestPath $ManifestPath
    }
    "po-api-smoke" {
        Invoke-ProductionOrderApiSmoke
    }
    "po-api-smoke-positive" {
        Invoke-ProductionOrderApiSmokePositive | Out-Null
    }
    "po-api-smoke-host-positive" {
        Invoke-HostProductionOrderApiSmokePositive | Out-Null
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
    "verify-host" {
        Write-Host "[verify-host] context guard..."
        Invoke-ContextGuard

        Write-Host "[verify-host] compile check..."
        Invoke-CompileCheck

        Write-Host "[verify-host] smoke tests..."
        Invoke-SmokeTests

        Write-Host "[verify-host] production-order host API smoke..."
        Invoke-HostProductionOrderApiSmokePositive | Out-Null

        Write-Host "[verify-host] OK"
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
    "verify-mvp" {
        Write-Host "[verify-mvp] context guard..."
        Invoke-ContextGuard

        Write-Host "[verify-mvp] compile check..."
        Invoke-CompileCheck

        Write-Host "[verify-mvp] smoke tests..."
        Invoke-SmokeTests

        $DockerAvailabilityMode = Get-DockerAvailabilityMode
        if ($DockerAvailabilityMode -eq "ready") {
            Write-Host "[verify-mvp] Docker daemon reachable, running live API smoke..."
            Invoke-ProductionOrderApiSmoke
            Write-Host "[verify-mvp] OK (live)"
            break
        }

        if ($DockerAvailabilityMode -eq "missing-cli") {
            Write-Host "[verify-mvp] docker CLI is not available, falling back to host API smoke..." -ForegroundColor Yellow
        }
        else {
            Write-Host "[verify-mvp] Docker daemon is not reachable, falling back to host API smoke..." -ForegroundColor Yellow
        }

        Write-Host "[verify-mvp] production-order host API smoke..."
        Invoke-HostProductionOrderApiSmokePositive | Out-Null

        Write-Host "[verify-mvp] OK (host)"
    }
    "verify-mvp-reports" {
        Write-Host "[verify-mvp-reports] context guard..."
        Invoke-ContextGuard

        Write-Host "[verify-mvp-reports] compile check..."
        Invoke-CompileCheck

        Write-Host "[verify-mvp-reports] generating first analytics report..."
        Invoke-HostMvpFirstAnalyticsReport
        $FirstAnalyticsReportDir = Get-LatestArtifactDirectory -RootPath (Join-Path (Get-Location).Path "artifacts\mvp_first_analytics")

        Write-Host "[verify-mvp-reports] generating live readiness report..."
        Invoke-HostMvpLiveReadinessReport
        $LiveReadinessReportDir = Get-LatestArtifactDirectory -RootPath (Join-Path (Get-Location).Path "artifacts\mvp_live_readiness")

        $VerificationTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $VerificationDir = Join-Path (Get-Location).Path "artifacts\mvp_report_verification\$VerificationTimestamp"
        New-Item -ItemType Directory -Force -Path $VerificationDir | Out-Null

        Write-Host "[verify-mvp-reports] writing verification manifest..."
        $ManifestOutput = python -m scripts.build_mvp_report_verification_manifest $FirstAnalyticsReportDir $LiveReadinessReportDir (Join-Path $VerificationDir "verification.json")
        if ($LASTEXITCODE -ne 0) {
            throw "[verify-mvp-reports] FAIL verification manifest step."
        }
        if ($ManifestOutput) {
            $ManifestOutput | ForEach-Object { Write-Host "[verify-mvp-reports] manifest: $_" }
        }

        Write-Host "[verify-mvp-reports] validating verification manifest..."
        $ManifestValidationOutput = python -m scripts.validate_mvp_report_verification_manifest (Join-Path $VerificationDir "verification.json")
        if ($LASTEXITCODE -ne 0) {
            throw "[verify-mvp-reports] FAIL verification manifest validation step."
        }
        if ($ManifestValidationOutput) {
            $ManifestValidationOutput | ForEach-Object { Write-Host "[verify-mvp-reports] manifest validation: $_" }
        }

        Write-Host "[verify-mvp-reports] verification directory: $VerificationDir"
        Write-Host "[verify-mvp-reports] OK"
    }
}
