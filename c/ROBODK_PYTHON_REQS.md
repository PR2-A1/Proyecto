# Requerimientos — Script Python RoboDK (integración GIIROB)

## Contexto

El script Python corre dentro de RoboDK y actúa como puente entre la simulación y el sistema MQTT. Tiene tres responsabilidades principales:

1. **Spawner de tapas** — recibe la orden del ESP32 y crea la tapa en la simulación.
2. **Cámara virtual** — detecta la tapa creada y publica su posición y color al ESP32.
3. **Robot Delta** — recibe la orden de pick del ESP32 y ejecuta el movimiento en la simulación.

Todo esto ocurre dentro del mismo proceso Python que RoboDK expone vía su API (`robolink`).

---

## Dependencias Python

| Librería | Uso |
|---|---|
| `robolink` | API oficial de RoboDK para controlar la simulación |
| `robomath` | Operaciones de matrices y poses de RoboDK |
| `paho-mqtt` | Cliente MQTT |
| `json` | Parseo de mensajes |
| `threading` | Bucle MQTT en hilo separado para no bloquear RoboDK |
| `time` | Delays entre movimientos |

---

## Conexión MQTT

| Parámetro | Valor |
|---|---|
| Broker | `broker.hivemq.com` |
| Puerto | `1883` |
| Client ID | `robodk-giirob` (o similar, debe ser único) |
| QoS | `1` (at least once) |

### Topics a suscribir

| Topic | Propósito |
|---|---|
| `giirob/pr2-A1/devices/robodk/action` | Recibir órdenes de spawn |
| `giirob/pr2-A1/devices/delta/action` | Recibir órdenes de pick para el Delta |
| `giirob/pr2-A1/system/emergency/status` | Pausar/reanudar ante emergencia |

### Topics a publicar

| Topic | Propósito |
|---|---|
| `giirob/pr2-A1/devices/camera/data` | Publicar detección de tapa tras el spawn |

---

## Comportamiento requerido

### 1. Spawn de tapa

**Disparado por:** mensaje en `giirob/pr2-A1/devices/robodk/action`

```json
{"cmd": "spawn", "color": "blue"}
```

**Acciones:**

1. Verificar que `cmd == "spawn"` (insensible a mayúsculas).
2. Leer el campo `color`. Valores válidos: `red`, `green`, `yellow`, `blue`, `white`, `orange`.
3. Crear el objeto de la tapa en la simulación de RoboDK con el color correspondiente (cambiar el color del objeto CAD o instanciar el modelo correcto según el color).
4. Posicionar la tapa en el punto de inicio de la cinta transportadora (posición fija conocida en la escena).
5. Esperar el tiempo necesario para que la animación de entrada sea coherente (configurable, ej. 0.5 s).
6. Publicar la detección al ESP32 en `giirob/pr2-A1/devices/camera/data`:

```json
{
  "x": 123.4,
  "y": 56.7,
  "color": "blue",
  "precision": 0.99,
  "cap_id": "cap_1"
}
```

| Campo | Valor |
|---|---|
| `x`, `y` | Coordenadas de la tapa en el sistema de referencia de la cámara (extraídas de la pose del objeto en RoboDK) |
| `color` | El mismo color que vino en el spawn, en minúsculas |
| `precision` | Valor fijo alto (ej. `0.99`) ya que la detección es simulada |
| `cap_id` | Identificador único incremental generado por el script (`cap_1`, `cap_2`, …) |

> El ESP32 ignorará la detección si `precision ≤ 0.95`, por lo que siempre debe enviarse un valor superior.

---

### 2. Pick del Delta

**Disparado por:** mensaje en `giirob/pr2-A1/devices/delta/action`

```json
{
  "cmd": "pick",
  "x": 123.4,
  "y": 56.7,
  "color": "blue",
  "tolva": "tolva_1",
  "cap_id": "cap_1",
  "reason": "..."
}
```

**Acciones:**

1. Verificar que `cmd == "pick"`.
2. Leer `x`, `y`, `color`, `tolva` y `cap_id`.
3. Si hay emergencia activa, descartar la orden (no ejecutar movimiento).
4. Mover el robot Delta a la posición `(x, y)` para recoger la tapa (movimiento de aproximación + pick).
5. Transportar la tapa al destino correspondiente a `tolva` (cada tolva tiene una posición fija en la escena).
6. Soltar la tapa (movimiento de place).
7. Regresar el Delta a su posición de home.
8. Eliminar o reubicar el objeto de la tapa en la simulación para mantener la escena limpia.
9. **No publicar nada** — la confirmación de entrega la hace el SCADA en `scada/status` con `cmd: "done"`.

> El script debe respetar el orden de los picks: si llega un segundo pick antes de terminar el primero, encolar la orden y ejecutarla al terminar.

---

### 3. Emergencia

**Disparado por:** mensaje en `giirob/pr2-A1/system/emergency/status`

```json
{"status": "active", "device": "ESP32-S3", "sensor": "emergency_button"}
```

```json
{"status": "operative", "device": "ESP32-S3", "sensor": "resume_button"}
```

**Acciones:**

- Si `status == "active"`: detener cualquier movimiento en curso lo antes posible. Activar bandera interna `emergency = True`. Rechazar nuevas órdenes de pick y spawn.
- Si `status == "operative"`: desactivar la bandera `emergency = False`. Retomar la cola de picks pendientes si la hay.

---

## Mapeo de colores a tolvas

El mismo mapeo que usa el ESP32:

| Color | Tolva |
|---|---|
| `red` | `tolva_1` |
| `yellow` | `tolva_2` |
| `green` | `tolva_3` |
| `white` | `tolva_4` |
| `orange` | `tolva_5` |
| `blue` | `tolva_6` |

El script puede usar esta tabla para validar que el destino del pick es coherente con el color de la tapa, pero **no debe rechazar la orden** si no coinciden — el ESP32 es la autoridad sobre el destino.

---

## Estructura recomendada del script

```
robodk_giirob.py
│
├── RoboDK setup          — conectar Robolink, obtener referencias a robot, objetos, targets
├── MQTT setup            — configurar cliente paho, suscribir topics
├── on_message()          — callback MQTT: despachar según topic
├── handle_spawn()        — crear tapa + publicar detección de cámara
├── handle_pick()         — encolar y ejecutar movimiento Delta
├── handle_emergency()    — activar/desactivar bandera de emergencia
├── pick_worker()         — hilo que consume la cola de picks
└── main loop             — mqtt.loop_forever() o loop en hilo + RoboDK.RunMessage()
```

---

## Consideraciones importantes

- **Hilo MQTT separado:** el bucle de MQTT (`loop_start()` o hilo manual) debe correr en paralelo al hilo de RoboDK para no bloquearse mutuamente.
- **Cola de picks:** usar `queue.Queue` de Python para serializar los movimientos del Delta sin perder órdenes.
- **cap_id único:** el script debe mantener un contador global para generar `cap_id` únicos (`cap_1`, `cap_2`, …) y correlacionar el spawn con la detección de cámara.
- **Posiciones en RoboDK:** todas las posiciones (home, punto de pick, tolvas) deben definirse como `Target` en la escena de RoboDK y referenciarse por nombre desde el script, no como coordenadas hardcodeadas.
- **Tiempo de ciclo:** el ESP32 espera la detección de cámara para procesar el pick. Si el spawn tarda demasiado, el sistema puede encolar tapas. El delay entre spawn y publicación de cámara debe ser coherente con la velocidad de la cinta en la simulación.
