#!/usr/bin/env bash
#
# install.sh — Instalador plug-and-play del monorepo PR2-A1.
#
# Instala ROS 2 Jazzy (ros-base) + Gazebo Harmonic + Nav2 y las dependencias
# del proyecto en una Ubuntu 24.04 (Noble) limpia, y compila el workspace colcon.
#
# Uso:
#   ./install.sh        # interactivo: muestra estimación de tamaño y pide confirmación
#   ./install.sh -y     # desatendido: omite la confirmación y no toca ~/.bashrc
#   ./install.sh -h     # ayuda
#
set -euo pipefail

# ---------- config ----------
export ROS_DISTRO="jazzy"
PKG_NAME="mir_nav2_robodk"
PKG_PATH="navegacion"

PY_APT_DEPS=(
  python3-pyqt5
  python3-paho-mqtt
  python3-opencv
  python3-numpy
  python3-psycopg2
  python3-dotenv
  python3-pymongo
)
BASE_APT_DEPS=(
  "ros-${ROS_DISTRO}-ros-base"
  ros-dev-tools
  python3-colcon-common-extensions
  python3-rosdep
  python3-pip
)

ASSUME_YES=0

# ---------- helpers ----------
log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

usage() {
  cat <<EOF
Uso: $0 [opciones]
  -y, --yes     Instalacion desatendida (omite confirmacion y no toca ~/.bashrc)
  -h, --help    Muestra esta ayuda
EOF
}

# ---------- parse flags ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Opcion desconocida: $1 (usa -h para ayuda)" ;;
  esac
done

# ---------- OS guard ----------
check_os() {
  local f="${OS_RELEASE_FILE:-/etc/os-release}"
  [[ -r "$f" ]] || die "No se encuentra $f; SO no soportado."
  # shellcheck disable=SC1090
  . "$f"
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
    die "Este software requiere Ubuntu 24.04 (Noble). Detectado: ${PRETTY_NAME:-desconocido}."
  fi
  log "SO verificado: ${PRETTY_NAME}"
}

check_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    warn "Ejecutando como root; se recomienda un usuario normal con sudo."
    SUDO=""
  else
    command -v sudo >/dev/null 2>&1 || die "Se necesita 'sudo' y no esta instalado."
    SUDO="sudo"
  fi
}

# ---------- repo location ----------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_repo() {
  [[ -f "${REPO_DIR}/${PKG_PATH}/package.xml" ]] \
    || die "No encuentro ${PKG_PATH}/package.xml en ${REPO_DIR}. Ejecuta el script desde el repo clonado."
  log "Repo: ${REPO_DIR}"
}

# ---------- steps ----------
install_prereqs() {
  log "Instalando prerrequisitos y locale..."
  $SUDO apt-get update
  $SUDO apt-get install -y curl gnupg lsb-release software-properties-common ca-certificates locales
  $SUDO locale-gen en_US en_US.UTF-8 || true
  $SUDO update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 || true
  $SUDO add-apt-repository -y universe
}

add_ros_repo() {
  log "Configurando repositorio de ROS 2..."
  $SUDO install -d -m 0755 /usr/share/keyrings
  if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
    curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      | $SUDO gpg --dearmor --yes -o /usr/share/keyrings/ros-archive-keyring.gpg
  fi
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu noble main" \
    | $SUDO tee /etc/apt/sources.list.d/ros2.list >/dev/null
}

add_gazebo_repo() {
  log "Configurando repositorio de Gazebo (OSRF)..."
  if [[ ! -f /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg ]]; then
    curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
      | $SUDO gpg --dearmor --yes -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  fi
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
    | $SUDO tee /etc/apt/sources.list.d/gazebo-stable.list >/dev/null
}

apt_update() {
  log "Actualizando indices apt..."
  $SUDO apt-get update
}

install_rosdep_tool() {
  log "Instalando rosdep..."
  $SUDO apt-get install -y python3-rosdep
}

setup_rosdep() {
  log "Inicializando rosdep..."
  if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
    $SUDO rosdep init
  fi
  rosdep update
}

# Imprime los paquetes apt que rosdep instalaria (uno por linea).
collect_ros_deps() {
  rosdep install --from-paths "${REPO_DIR}/${PKG_PATH}" --ignore-src --reinstall -y -s 2>/dev/null \
    | sed -n 's/^.*apt-get install -y //p' \
    | tr ' ' '\n' \
    | grep -vE '^-|^$' \
    | sort -u
}

show_estimate_and_confirm() {
  log "Calculando tamano de la instalacion (puede tardar unos segundos)..."
  local ros_deps union sim count get disk
  mapfile -t ros_deps < <(collect_ros_deps || true)
  union="$(printf '%s\n' "${BASE_APT_DEPS[@]}" "${PY_APT_DEPS[@]}" "${ros_deps[@]}" | sort -u | tr '\n' ' ')"

  # shellcheck disable=SC2086
  sim="$($SUDO apt-get install -s $union 2>/dev/null || true)"
  count="$(printf '%s\n' "$sim" | grep -c '^Inst ' || true)"
  get="$(printf '%s\n' "$sim" | sed -n 's/^Need to get \(.*\)\./\1/p' | head -1)"
  disk="$(printf '%s\n' "$sim" | sed -n 's/^After this operation, \(.*\) will be used.*/\1/p' | head -1)"

  echo
  echo "==================== ADVERTENCIA ===================="
  echo " Esta instalacion anadira software del sistema:"
  echo " ROS 2 Jazzy, Gazebo Harmonic, Nav2 y dependencias."
  echo "   Paquetes nuevos a instalar : ${count:-?}"
  echo "   Descarga aproximada        : ${get:-no determinada}"
  echo "   Espacio en disco           : ${disk:-no determinado}"
  echo " Ademas: 'robodk' via pip (opcional) y compilacion del workspace."
  echo "====================================================="
  echo

  if [[ "$ASSUME_YES" -eq 1 ]]; then
    log "Modo desatendido (-y): continuando sin confirmacion."
    return 0
  fi
  read -r -p "Continuar con la instalacion? [y/N] " ans
  [[ "$ans" =~ ^[yY]$ ]] || die "Instalacion cancelada por el usuario."
}

install_base() {
  log "Instalando ROS 2 base y herramientas de build..."
  $SUDO apt-get install -y "${BASE_APT_DEPS[@]}"
}

install_ros_deps() {
  log "Instalando dependencias ROS del paquete (rosdep)..."
  rosdep install --from-paths "${REPO_DIR}/${PKG_PATH}" --ignore-src -y
}

install_python_deps() {
  log "Instalando dependencias de Python (apt)..."
  $SUDO apt-get install -y "${PY_APT_DEPS[@]}"
  log "Instalando 'robodk' (pip, opcional)..."
  if ! pip install robodk --break-system-packages; then
    warn "No se pudo instalar 'robodk' por pip; el bridge funcionara sin RoboDK."
  fi
}

build_workspace() {
  log "Compilando el workspace con colcon..."
  # shellcheck disable=SC1090,SC1091
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
  ( cd "$REPO_DIR" && colcon build --packages-select "$PKG_NAME" )
}

maybe_update_bashrc() {
  local line="source /opt/ros/${ROS_DISTRO}/setup.bash"
  if grep -qF "$line" "${HOME}/.bashrc" 2>/dev/null; then
    return 0
  fi
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi
  read -r -p "Anadir '${line}' a ~/.bashrc? [y/N] " ans
  if [[ "$ans" =~ ^[yY]$ ]]; then
    printf '\n# ROS 2 %s\n%s\n' "$ROS_DISTRO" "$line" >> "${HOME}/.bashrc"
    log "Anadido a ~/.bashrc."
  fi
}

summary() {
  echo
  log "Instalacion completada."
  cat <<EOF

Para lanzar el sistema:

  source /opt/ros/${ROS_DISTRO}/setup.bash
  cd "${REPO_DIR}"
  source install/setup.bash
  ros2 launch ${PKG_NAME} bringup.launch.py

EOF
}

main() {
  check_os
  check_sudo
  check_repo
  install_prereqs
  add_ros_repo
  add_gazebo_repo
  apt_update
  install_rosdep_tool
  setup_rosdep
  show_estimate_and_confirm
  install_base
  install_ros_deps
  install_python_deps
  build_workspace
  maybe_update_bashrc
  summary
}

main "$@"
