param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("up", "ps", "logs", "test", "health", "proposal", "context")]
    [string]$Command
)

$ComposeFile = ".\\docker-compose.yml"

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
        $BaseRef = git merge-base HEAD origin/main 2>$null
        if (-not $BaseRef) {
            $BaseRef = "HEAD~1"
        }

        python .\scripts\context_guard.py --base $BaseRef.Trim() --head HEAD
    }
}
