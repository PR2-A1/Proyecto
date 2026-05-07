# Lanza el firmware ESP32 y el bridge MQTT-DB en terminales separadas
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Detectar el target nativo del host para no heredar el target ESP32 de la raiz
$nativeTarget = (rustc -vV | Select-String "host:").ToString().Trim().Split(" ")[1]

# Bridge MQTT-DB con target nativo explícito
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\mqtt_db_bridge'; cargo run --target $nativeTarget"

# Firmware ESP32 (flashea y abre monitor serie)
cargo run
