# ============================================================
# Demo Escenarios de Integración — Windows
# Uso: .\run_demo.ps1
#      .\run_demo.ps1 -SkipDb   (si los datos ya están cargados)
# ============================================================
param(
    [switch]$SkipDb
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ------------------------------------------------------------
# Localizar psql.exe (busca en todas las versiones instaladas)
# ------------------------------------------------------------
$psql = Get-ChildItem "C:\Program Files\PostgreSQL" -Filter "psql.exe" -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName

if (-not $psql) {
    Write-Host "ERROR: psql.exe no encontrado en C:\Program Files\PostgreSQL" -ForegroundColor Red
    Write-Host "       Instala PostgreSQL o añade su carpeta bin al PATH"
    exit 1
}
Write-Host "psql encontrado: $psql" -ForegroundColor Gray

# ------------------------------------------------------------
# 1. Cargar datos de prueba en la BD (operarios, lotes, cajas)
# ------------------------------------------------------------
if (-not $SkipDb) {
    Write-Host "Cargando datos de prueba en la BD..." -ForegroundColor Cyan

    # Leer parámetros de conexión del .env del bridge
    $envFile = "$root\bridge\.env"
    if (-not (Test-Path $envFile)) {
        Write-Host "ERROR: No existe $envFile" -ForegroundColor Red
        Write-Host "       Copia bridge\.env.example a bridge\.env y rellena DATABASE_URL"
        exit 1
    }

    # Parsear DATABASE_URL con formato: host=X user=Y password=Z dbname=W
    $dbLine = (Get-Content $envFile | Where-Object { $_ -match "^DATABASE_URL=" }) -replace "^DATABASE_URL=", ""
    if (-not $dbLine) {
        Write-Host "ERROR: DATABASE_URL no encontrada en $envFile" -ForegroundColor Red
        exit 1
    }

    # Soporta formato URI: postgres://user:pass@host/dbname
    if ($dbLine -match "^postgres(?:ql)?://([^:]+):([^@]*)@([^/:]+)(?::\d+)?/(\S+)$") {
        $dbUser = $Matches[1]
        $dbPass = $Matches[2]
        $dbHost = $Matches[3]
        $dbName = $Matches[4]
    } else {
        $dbHost = if ($dbLine -match "host=(\S+)")     { $Matches[1] } else { "127.0.0.1" }
        $dbUser = if ($dbLine -match "user=(\S+)")     { $Matches[1] } else { "postgres"  }
        $dbPass = if ($dbLine -match "password=(\S+)") { $Matches[1] } else { ""          }
        $dbName = if ($dbLine -match "dbname=(\S+)")   { $Matches[1] } else { "giirob"    }
    }

    $env:PGPASSWORD = $dbPass

    # Crear la BD si no existe
    Write-Host "  Creando base de datos '$dbName' si no existe..." -ForegroundColor Gray
    & $psql -h $dbHost -U $dbUser -d postgres -c "CREATE DATABASE `"$dbName`";" 2>$null
    # Ignorar error si ya existe

    # Aplicar schema completo (tablas + datos de prueba)
    Write-Host "  Aplicando schema y datos de prueba..." -ForegroundColor Gray
    & $psql -h $dbHost -U $dbUser -d $dbName -f "$root\db\schema.sql"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR ejecutando schema. Verifica la conexion a PostgreSQL." -ForegroundColor Red
        exit 1
    }

    Write-Host "  BD lista." -ForegroundColor Green
    $env:PGPASSWORD = ""
}

# ------------------------------------------------------------
# 2. Detectar target nativo (para no heredar el target ESP32)
# ------------------------------------------------------------
$nativeTarget = (rustc -vV | Select-String "host:").ToString().Trim().Split(" ")[1]
Write-Host "Target nativo detectado: $nativeTarget" -ForegroundColor Gray

# ------------------------------------------------------------
# 3. Lanzar bridge en una terminal separada
# ------------------------------------------------------------
Write-Host "Iniciando bridge MQTT-DB..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root\bridge'; cargo run --target $nativeTarget"

Start-Sleep -Seconds 2

# ------------------------------------------------------------
# 4. Flashear firmware ESP32 en la terminal actual
# ------------------------------------------------------------
Write-Host "Flasheando ESP32..." -ForegroundColor Cyan
Set-Location "$root\esp32"
cargo run
