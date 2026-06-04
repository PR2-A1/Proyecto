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

**No hace falta instalar nada a mano.** El script `install.sh` de la raíz se encarga
de instalar **todas las dependencias** del proyecto por ti. En una Ubuntu 24.04 limpia,
clona el repo y ejecútalo:

```bash
git clone git@github.com:ETM2097/Proyecto.git
cd Proyecto
./install.sh          # muestra el tamaño estimado y pide confirmación
# ./install.sh -y     # instalación desatendida (sin preguntas)
```

`install.sh` instala y deja todo listo:

- **ROS 2 Jazzy** (base) y las **herramientas de build** (colcon, rosdep).
- **Gazebo Harmonic**, **Nav2**, **RViz** y demás dependencias ROS del paquete
  (resueltas automáticamente desde `navegacion/package.xml`).
- Las **dependencias de Python** (PyQt5, paho-mqtt, OpenCV, numpy, psycopg2,
  python-dotenv, pymongo) y, opcionalmente, `robodk`.
- **Compila el workspace** (`colcon build`) al terminar.

Antes de instalar nada, avisa del número de paquetes y del espacio en disco, y pide
confirmación. Tras ejecutarlo, salta directamente a [Lanzar la simulación](#lanzar-la-simulación-completa).

## Lanzar la simulación completa

Si has ejecutado `install.sh`, las dependencias ya están instaladas y el workspace
compilado: solo tienes que hacer `source` y lanzar.

```bash
# Desde la raíz del repo
source install/setup.bash

# Arranca TODO: Gazebo + MiR + Nav2 + RViz + bridge RoboDK-MQTT + SCADA
ros2 launch mir_nav2_robodk bringup.launch.py
```

> ¿No usaste el instalador o cambiaste código? Recompila antes con
> `colcon build --packages-select mir_nav2_robodk`

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