# Windows equivalent of start-all.sh, which is macOS-only (it hardcodes
# /Library/Frameworks/Python..., uses lsof, and logs to /tmp).
#
# Two deliberate differences from the .sh, both forced by this machine:
#   * Postgres runs as a SECOND, userspace cluster on 5433. The Program Files
#     PG16 service on 5432 has no tentoroforge role and its superuser password
#     is unknown, and creating one needs Administrator. initdb'ing our own
#     cluster needs neither, and leaves that service untouched.
#   * Schema comes from SQLAlchemy create_all, not `alembic upgrade head` --
#     the migration graph raises KeyError 'd1e2f3a4b5c6' on a fresh database.
#     Alembic is stamped to head afterwards so future migrations still apply.

$ErrorActionPreference = "Stop"
$Root   = $PSScriptRoot
$PgBin  = "C:\Program Files\PostgreSQL\16\bin"
$PgData = "C:\Users\user\forge-pgdata"
$Logs   = Join-Path $env:TEMP "tentoroforge-logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Free-Port($port) {
  Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue
                     "  freed port $port (pid $($_.OwningProcess))" }
}

function Wait-Url($url, $label, $timeout = 120) {
  foreach ($i in 1..$timeout) {
    try { Invoke-WebRequest $url -TimeoutSec 5 -UseBasicParsing | Out-Null
          "  OK  $label"; return $true } catch { Start-Sleep -Seconds 1 }
  }
  "  --  $label did not come up in ${timeout}s"; return $false
}

"> Postgres (userspace cluster on 5433)..."
& "$PgBin\pg_isready.exe" -h 127.0.0.1 -p 5433 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Start-Process -FilePath "$PgBin\pg_ctl.exe" -WindowStyle Hidden `
    -ArgumentList "-D","$PgData","-l","$PgData\server.log","-o","-p 5433","start"
  Start-Sleep -Seconds 5
}
"  postgres ready on 5433"

"> Stopping anything on 6500-6503, 6600..."
6500,6501,6502,6503,6600 | ForEach-Object { Free-Port $_ }

$env:CLAUDE_CODE_MAX_OUTPUT_TOKENS = "64000"
$env:FORGE_SELF_VERIFY             = "1"
$env:FORGE_VERIFY_URL              = "http://localhost:6600"
$env:FORGE_INTERNAL_BASE_URL       = "http://localhost:6500"
$env:FORGE_AUTOFIX_V2              = "1"
$env:FORGE_AUTOFIX_SMITH_BUDGET    = "15"

# backend/.env carries ANTHROPIC_API_KEY + DATABASE_URL; uvicorn's process
# needs them exported, and python-dotenv only loads them inside the app.
Get-Content "$Root\backend\.env" | ForEach-Object {
  if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
    Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim('"').Trim("'")
  }
}

"> backend (:6500)"
Start-Process python -WorkingDirectory "$Root\backend" -WindowStyle Hidden `
  -ArgumentList "-m","uvicorn","main:app","--port","6500","--host","0.0.0.0" `
  -RedirectStandardOutput "$Logs\backend.log" -RedirectStandardError "$Logs\backend.err"

"> render-service (:6502)"
Start-Process python -WorkingDirectory "$Root\backend" -WindowStyle Hidden `
  -ArgumentList "-m","services.render_service" `
  -RedirectStandardOutput "$Logs\render-service.log" -RedirectStandardError "$Logs\render-service.err"

"> frontend (:6501)"
# The eye/preview button builds "${NEXT_PUBLIC_PREVIEW_URL}/p/<id><route>".
# Unset, that base is "" and the URL is relative -- so it resolves against the
# PLATFORM origin (:6501), which has no /p route, and every preview 404s. On
# UAT caddy routes /p/* to the scaffold and same-origin is right; locally
# there is no proxy, so the scaffold has to be named explicitly.
$env:NEXT_PUBLIC_PREVIEW_URL = "http://localhost:6503"
Start-Process "$Root\node_modules\.bin\next.cmd" -WorkingDirectory "$Root\frontend" -WindowStyle Hidden `
  -ArgumentList "dev","-p","6501" `
  -RedirectStandardOutput "$Logs\frontend.log" -RedirectStandardError "$Logs\frontend.err"

"> render-scaffold (:6503)"
$env:NODE_OPTIONS = "--max-old-space-size=4096"
# /p IS THE SCAFFOLD'S PATH EVERYWHERE ELSE. render_service builds
# "{scaffold}/p/{projectId}{route}" and fidelity_runner "{scaffold}/p/{id}/{slug}";
# next.config only applies the prefix when NEXT_BASE_PATH is set. Without it
# the scaffold serves at the root and every one of those URLs 404s.
$env:NEXT_BASE_PATH = "/p"
Start-Process "$Root\node_modules\.bin\next.cmd" -WorkingDirectory "$Root\apps\render-scaffold" -WindowStyle Hidden `
  -ArgumentList "dev","-p","6503" `
  -RedirectStandardOutput "$Logs\scaffold.log" -RedirectStandardError "$Logs\scaffold.err"

"> forge-verify (:6600)"
$env:PORT = "6600"; $env:FORGE_VERIFY_MAX_CONTEXTS = "6"
Start-Process "npx.cmd" -WorkingDirectory "$Root\docker\forge-verify" -WindowStyle Hidden `
  -ArgumentList "tsx","src/server.ts" `
  -RedirectStandardOutput "$Logs\forge-verify.log" -RedirectStandardError "$Logs\forge-verify.err"

""
"> Waiting for services (Next compiles on first request; allow ~2 min)..."
Wait-Url "http://localhost:6500/health"  "backend        :6500" 60  | Out-Null
Wait-Url "http://localhost:6502/health"  "render-service :6502" 60  | Out-Null
Wait-Url "http://localhost:6600/healthz" "forge-verify   :6600" 60  | Out-Null
Wait-Url "http://localhost:6501/"        "frontend       :6501" 180 | Out-Null
# basePath /p — the scaffold no longer answers at the root.
Wait-Url "http://localhost:6503/p"       "render-scaffold:6503" 180 | Out-Null

@"

--------------------------------------------------------------------
Tentoro Forge is up.

  Frontend (editor) .... http://localhost:6501
  Backend API .......... http://localhost:6500
  Render service ....... http://localhost:6502
  Render scaffold ...... http://localhost:6503
  Forge-verify (SV) .... http://localhost:6600
  Postgres ............. localhost:5433 (userspace cluster)

Logs: $Logs
Stop: 6500,6501,6502,6503,6600 | ForEach-Object { Get-NetTCPConnection -LocalPort `$_ -State Listen -EA SilentlyContinue | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force } }
--------------------------------------------------------------------
"@
