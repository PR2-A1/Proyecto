# `robodk_bridge` — Guía de funcionamiento

Nodo ROS 2 que conecta RoboDK con Nav2 de forma **bidireccional**:

- **RoboDK → ROS**: lee destinos de navegación publicados por RoboDK y los
  envía como goals a `navigate_to_pose`.
- **ROS → RoboDK**: lee la pose del robot desde TF (`map` → `base_link`)
  y actualiza el gemelo digital en la estación de RoboDK.

> Este nodo reemplaza funcionalmente a `robodk_position_sender` cuando se
> necesita la entrada de destinos desde RoboDK. **No** lances ambos a la
> vez: los dos escribirían la pose del mismo item.

---

## 1. Flujo general

```
   RoboDK station                              ROS 2
+--------------------+      poll (2 Hz)      +------------------+
| NAV_TARGET = ...   | ───────────────────► | robodk_bridge    |
| ORDER_NAV_RECEIVED | ◄─── ack / clear ─── |                  |
| GOAL_NAV_REACHED   | ◄── navigation done ─|     ▼            |
|                    |                       | navigate_to_pose |
|  MiR (ITEM_ROBOT)  | ◄─ setJoints 30 Hz ── | (Nav2 action)    |
+--------------------+       (TF → twin)     +------------------+
```

---

## 2. Entradas (RoboDK → Nav2)

El nodo acepta destinos por **dos caminos** en paralelo:

### 2.1 Parámetro de estación `NAV_TARGET` (recomendado)

RoboDK escribe un string plano en el parámetro de estación definido por
`target_var_name` (por defecto `NAV_TARGET`). El bridge lo sondea a
`poll_rate` Hz.

**Formato**:

```
X:<metros>,Y:<metros>[,YAW:<grados>]
```

Ejemplos válidos:

```
X:3.5,Y:2.0
X:3.5,Y:2.0,YAW:90
X:-1.25,Y:0.4,YAW:-180
```

Formato **legacy** (aceptado por compatibilidad):

```
X:3.5,Y:2.0,Z:90          # Z se interpreta como yaw en grados si no hay YAW:
```

Ignora claves desconocidas y espacios. Si el string es malformado, se
loguea un warning y se descarta (sin reintentos) hasta que cambie.

### 2.2 Tópico ROS `robodk/target_name`

Publica en `robodk/target_name` (`std_msgs/String`) el **nombre** de un
`ITEM_TYPE_TARGET` existente en la estación. El bridge lo busca por
nombre, extrae `item.PoseAbs()` (pose absoluta en la raíz de la
estación) y lo convierte en un goal Nav2.

```bash
ros2 topic pub --once /robodk/target_name std_msgs/String "data: 'Dock_A'"
```

### 2.3 Tópico ROS `goal_pose` (RViz)

Los goals de RViz siguen funcionando en paralelo. El bridge los
reenvía tal cual a Nav2 — útil para probar la localización sin tocar
RoboDK.

---

## 3. Handshake con RoboDK

Cuando llega una orden nueva por `NAV_TARGET`, el bridge escribe en la
estación:

| Parámetro             | Cuándo                        | Valor   |
|-----------------------|-------------------------------|---------|
| `ORDER_NAV_RECEIVED`  | Goal parseado correctamente   | `True`  |
| `GOAL_NAV_REACHED`    | Goal parseado (reset)         | `False` |
| `NAV_TARGET`          | Nav2 acepta el goal           | `""`    |
| `GOAL_NAV_REACHED`    | Nav2 termina con éxito (4)    | `True`  |

RoboDK puede esperar `ORDER_NAV_RECEIVED==True` para saber que el
bridge leyó la orden, y `GOAL_NAV_REACHED==True` para saber que el
robot llegó. El `NAV_TARGET=""` tras aceptar el goal permite reenviar
el mismo destino más tarde sin que el bridge lo deduplique.

---

## 4. Salida (TF → RoboDK)

A `twin_update_rate` Hz (30 Hz por defecto) el bridge consulta TF
`global_frame → robot_frame`, convierte a milímetros/grados y escribe:

- Si el item es `ITEM_TYPE_ROBOT` (mecanismo móvil):
  `setJoints([x_mm, y_mm, 0, yaw_deg])`.
- Si es `ITEM_TYPE_FRAME` u otro: `setPoseAbs(TxyzRxyz_2_Pose(...))`.

Si `freeze_yaw=true`, el yaw se fuerza a `0°` (útil cuando RoboDK ya
orienta el modelo por IK y sólo interesa la posición).

---

## 5. Estados publicados (`robodk/status`)

`std_msgs/String` con transiciones del ciclo de vida:

| Valor                | Significado                                   |
|----------------------|-----------------------------------------------|
| `connected`          | Conexión con RoboDK establecida               |
| `disconnected`       | No se pudo conectar / caída de conexión       |
| `navigating`         | Goal enviado a Nav2 en curso                  |
| `goal_reached`       | Navegación finalizada con éxito               |
| `goal_rejected`      | Nav2 rechazó el goal                          |
| `nav2_unavailable`   | Action server no disponible en 5 s            |
| `nav_status_<code>`  | Resultado Nav2 distinto de éxito              |

---

## 6. Parámetros

| Parámetro            | Tipo  | Default      | Descripción                              |
|----------------------|-------|--------------|------------------------------------------|
| `robodk_host`        | str   | `localhost`  | Host del API de RoboDK                   |
| `robodk_port`        | int   | `20500`      | Puerto del API                           |
| `poll_rate`          | float | `2.0`        | Hz de lectura de `NAV_TARGET`            |
| `station_name`       | str   | `""`         | Filtro por estación (informativo)        |
| `robot_item_name`    | str   | `MiR`        | Nombre del item a actualizar             |
| `target_var_name`    | str   | `NAV_TARGET` | Parámetro de estación que se sondea      |
| `global_frame`       | str   | `map`        | TF global                                |
| `robot_frame`        | str   | `base_link`  | TF del robot                             |
| `twin_update_rate`   | float | `30.0`       | Hz de actualización del gemelo digital   |
| `freeze_yaw`         | bool  | `false`      | Si `true`, no actualiza el yaw en RoboDK |

---

## 7. Arranque

```bash
# RoboDK en la misma máquina
ros2 run mir_nav2_robodk robodk_bridge.py

# RoboDK en otra máquina
ros2 run mir_nav2_robodk robodk_bridge.py --ros-args \
  -p robodk_host:=192.168.1.100 \
  -p robot_item_name:=MiR \
  -p twin_update_rate:=20.0
```

Prerrequisitos:

- Nav2 levantado (`navigate_to_pose` action server disponible).
- TF `map → base_link` publicado (AMCL o SLAM).
- RoboDK abierto con el API activo (menú *Options → Other → Run API on
  startup* y el puerto `20500` libre).
- Python: `pip install robodk`.

---

## 8. Ejemplo de uso end-to-end

Terminal A — navegación:

```bash
ros2 launch mir_nav2_robodk bringup.launch.py \
  map:=$HOME/mir_robodk_ws/src/mir_nav2_robodk/maps/my_map.yaml
```

Terminal B — bridge:

```bash
ros2 run mir_nav2_robodk robodk_bridge.py
```

Terminal C — enviar un destino manualmente (simulando RoboDK):

```bash
python3 - <<'PY'
from robodk.robolink import Robolink
rdk = Robolink()
rdk.setParam('NAV_TARGET', 'X:3.5,Y:2.0,YAW:90')
PY
```

El bridge loguea:

```
[INFO] RoboDK target received: X:3.5,Y:2.0,YAW:90
[INFO] Nav2 goal accepted, navigating...
[INFO] Distance remaining: 2.14m
[INFO] Navigation goal reached!
```

y, mientras tanto, el icono del robot en RoboDK se mueve a 30 Hz.

---

## 9. Diagnóstico

| Síntoma                                      | Causa probable                            | Solución                                                         |
|----------------------------------------------|-------------------------------------------|------------------------------------------------------------------|
| `Cannot connect to RoboDK`                   | API no corriendo o host/puerto erróneo    | Verifica `robodk_host`, `robodk_port`; arranca el API en RoboDK  |
| `Robot item "MiR" not found`                 | Nombre del item distinto                  | Pasa `-p robot_item_name:=<nombre_exacto>`                       |
| `Malformed target string`                    | Formato `NAV_TARGET` incorrecto           | Usa `X:<m>,Y:<m>,YAW:<deg>`                                      |
| El twin no se mueve                          | Falta TF `map → base_link`                | Comprueba con `ros2 run tf2_tools view_frames`                   |
| `Nav2 navigate_to_pose action server not available` | Nav2 no levantado                  | Lanza `bringup.launch.py` o `simulation.launch.py`               |
| Goal se descarta silenciosamente             | Mismo string que el anterior              | RoboDK debe vaciar `NAV_TARGET` o cambiar el valor               |
| El gemelo se bambolea en orientación         | Yaw publicado por AMCL ruidoso            | Pon `freeze_yaw:=true` o baja `twin_update_rate`                 |

---

## 10. Diferencias frente a `robodk_position_sender`

| Aspecto                        | `robodk_bridge`              | `robodk_position_sender`          |
|--------------------------------|------------------------------|-----------------------------------|
| Dirección                      | Bidireccional                | Solo ROS → RoboDK                 |
| Entrada de goals desde RoboDK  | Sí (`NAV_TARGET` y topic)    | No                                |
| Actualiza el twin desde TF     | Sí (30 Hz)                   | Sí                                |
| `only_while_navigating`        | No                           | Sí                                |
| `freeze_yaw`                   | Sí                           | Sí                                |
| Handshake con RoboDK           | Sí (tres parámetros)         | No                                |

Usa `robodk_position_sender` si RoboDK es solo visualización. Usa
`robodk_bridge` si RoboDK también decide a dónde ir.
