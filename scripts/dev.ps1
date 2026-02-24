param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("up", "ps", "logs", "test", "health", "proposal", "context", "verify")]
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
}
