#!/bin/bash
# ============================================================
# Demo Escenarios de Integración — macOS
# Uso: ./run_demo.sh
#      ./run_demo.sh --skip-db   (si los datos ya están cargados)
# ============================================================

ROOT="$(cd "$(dirname "$0")" && pwd)"
SKIP_DB=false

for arg in "$@"; do
    case $arg in
        --skip-db) SKIP_DB=true ;;
    esac
done

# Colores
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
GRAY='\033[0;37m'
NC='\033[0m'

# ------------------------------------------------------------
# 1. Cargar datos de prueba en la BD
# ------------------------------------------------------------
if [ "$SKIP_DB" = false ]; then
    echo -e "${CYAN}Cargando datos de prueba en la BD...${NC}"

    ENV_FILE="$ROOT/bridge/.env"
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}ERROR: No existe $ENV_FILE${NC}"
        echo "       Copia bridge/.env.example a bridge/.env y rellena DATABASE_URL"
        exit 1
    fi

    DB_URL=$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d'=' -f2-)
    if [ -z "$DB_URL" ]; then
        echo -e "${RED}ERROR: DATABASE_URL no encontrada en $ENV_FILE${NC}"
        exit 1
    fi

    echo -e "${GRAY}  Aplicando schema real...${NC}"
    psql "$DB_URL" -f "$ROOT/../mqtt_db_bridge/schema.sql"
    if [ $? -ne 0 ]; then
        echo -e "${RED}ERROR aplicando schema. Verifica la conexion a PostgreSQL.${NC}"
        exit 1
    fi

    echo -e "${GRAY}  Insertando datos de prueba...${NC}"
    psql "$DB_URL" -f "$ROOT/db/schema.sql"
    if [ $? -ne 0 ]; then
        echo -e "${RED}ERROR insertando datos de prueba.${NC}"
        exit 1
    fi

    echo -e "${GREEN}  BD lista.${NC}"
fi

# ------------------------------------------------------------
# 2. Detectar target nativo del host
# ------------------------------------------------------------
NATIVE_TARGET=$(rustc -vV | sed -n 's|host: ||p')
echo -e "${GRAY}Target nativo: $NATIVE_TARGET${NC}"

# ------------------------------------------------------------
# 3. Lanzar bridge en nueva ventana de Terminal
# ------------------------------------------------------------
echo -e "${CYAN}Iniciando bridge MQTT-DB...${NC}"

BRIDGE_SCRIPT="$ROOT/_run_bridge.sh"
cat > "$BRIDGE_SCRIPT" << EOF
#!/bin/bash
cd "$ROOT/bridge"
cargo run --target $NATIVE_TARGET
EOF
chmod +x "$BRIDGE_SCRIPT"

osascript -e "tell application \"Terminal\" to do script \"$BRIDGE_SCRIPT\""
sleep 2

# ------------------------------------------------------------
# 4. Flashear firmware ESP32 (requiere entorno esp-idf)
# ------------------------------------------------------------
echo -e "${CYAN}Flasheando ESP32...${NC}"

# Cargar el entorno de ESP-IDF/Espressif si existe
if [ -f "$HOME/export-esp.sh" ]; then
    source "$HOME/export-esp.sh"
fi

cd "$ROOT/esp32"
cargo run
