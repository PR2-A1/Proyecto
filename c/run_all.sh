#!/bin/bash
# Lanza el bridge MQTT-DB en una terminal separada y el firmware ESP32 en la actual

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Detectar el target nativo del host (ej: aarch64-apple-darwin, x86_64-apple-darwin)
NATIVE_TARGET=$(rustc -vV | sed -n 's|host: ||p')

# Script temporal para el bridge — usa el target nativo para no heredar el target ESP32 de la raíz
BRIDGE_SCRIPT="$ROOT/_run_bridge.sh"
cat > "$BRIDGE_SCRIPT" << EOF
#!/bin/bash
cd "$ROOT/mqtt_db_bridge"
cargo run --target $NATIVE_TARGET
EOF
chmod +x "$BRIDGE_SCRIPT"

# Abrir el bridge en una nueva ventana de Terminal
osascript -e "tell application \"Terminal\" to do script \"$BRIDGE_SCRIPT\""

# Cargar entorno ESP y lanzar firmware en la terminal actual
source ~/export-esp.sh
cd "$ROOT"
cargo run
