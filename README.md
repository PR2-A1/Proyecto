# Proyecto PR2-A1 — Célula robotizada (monorepo)

Monorepo del proyecto, organizado por subsistemas.

## Requisitos

- **Ubuntu 24.04 LTS (Noble Numbat)** — imprescindible. El software está pensado y
  probado solo para esta versión; el instalador aborta en cualquier otra.
- Conexión a internet (la instalación descarga varios GB de paquetes).

## Estructura

| Carpeta | Subsistema |
|---|---|
| `navegacion/` | Paquete ROS2 `mir_nav2_robodk`: simulación Gazebo del AMR (MiR), Nav2, bridge RoboDK-MQTT-ROS2 y SCADA. |
| `comunicaciones/` | Firmware ESP-IDF/Arduino (`c/`) y documentación (`d/`). |
| `database/` | Puente MQTT↔SQL/noSQL y esquema de base de datos. |

## Instalación

En una Ubuntu 24.04 limpia, clona el repo y ejecuta el instalador. Instala ROS 2
Jazzy, Gazebo Harmonic, Nav2 y todas las dependencias, y compila el workspace.

```bash
git clone git@github.com:ETM2097/Proyecto.git
cd Proyecto
./install.sh          # muestra el tamaño estimado y pide confirmación
# ./install.sh -y     # instalación desatendida (sin preguntas)
```

El instalador avisa del número de paquetes y del espacio en disco antes de instalar.

## Lanzar la simulación completa

Requisitos: ROS2 Jazzy, Gazebo Harmonic, Nav2. El paquete `navegacion/` se
compila con colcon (se encuentra automáticamente aunque esté anidado).

```bash
# Desde la raíz del repo (o desde tu workspace colcon que contenga este repo en src/)
colcon build --packages-select mir_nav2_robodk
source install/setup.bash

# Arranca TODO: Gazebo + MiR + Nav2 + RViz + bridge RoboDK-MQTT + SCADA
ros2 launch mir_nav2_robodk bringup.launch.py
```

### Apagar piezas concretas

```bash
ros2 launch mir_nav2_robodk bringup.launch.py bridge:=false scada:=false rviz:=false
```

### Argumentos principales

| Argumento | Default | Descripción |
|---|---|---|
| `slam` | `True` | SLAM (True) o localización con mapa (False) |
| `world` | `station.sdf` | Mundo de Gazebo |
| `map` | `warehouse.yaml` | Mapa para localización (si `slam:=False`) |
| `rviz` | `true` | Lanzar RViz |
| `bridge` | `true` | Lanzar el bridge RoboDK-MQTT |
| `scada` | `true` | Lanzar la app SCADA |
| `mqtt_host` | `broker.hivemq.com` | Broker MQTT |
| `robodk_host` | `localhost` | Host de la API de RoboDK |

## Otros subsistemas

- **comunicaciones**: ver `comunicaciones/README.md`.
- **database**: ver scripts en `database/` (`bridge.py`, `db_structure.sql`, `queries.sql`).
