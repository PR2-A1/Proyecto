# GIIROB — Documentación del sistema

Sistema de clasificación automática de tapas industriales compuesto por dos componentes: un firmware embebido para ESP32-S3 y un servicio de puente MQTT-PostgreSQL.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Firmware ESP32-S3 (prueba2)](#2-firmware-esp32-s3-prueba2)
   - [Arquitectura de tareas](#21-arquitectura-de-tareas)
   - [Modos de operación](#22-modos-de-operación)
   - [Gestión Wi-Fi](#23-gestión-wi-fi)
   - [Gestión MQTT](#24-gestión-mqtt)
   - [Topics MQTT](#25-topics-mqtt)
   - [Comandos recibidos](#26-comandos-recibidos)
   - [Tarea de lógica](#27-tarea-de-lógica)
   - [Sistema de tolvas](#28-sistema-de-tolvas)
   - [Coordinación AMR](#29-coordinación-amr)
   - [Coordinación Cobot](#210-coordinación-cobot)
   - [Sistema de emergencia](#211-sistema-de-emergencia)
   - [Persistencia NVS](#212-persistencia-nvs)
   - [Estado compartido (ControlState)](#213-estado-compartido-controlstate)
3. [Puente MQTT-PostgreSQL (mqtt_db_bridge)](#3-puente-mqtt-postgresql-mqtt_db_bridge)
   - [Función](#31-función)
   - [Topics escuchados](#32-topics-escuchados)
   - [Evento box_completed](#33-evento-box_completed)
   - [Evento caja_paletizada](#34-evento-caja_paletizada)
   - [Evento tapa_clasificada](#35-evento-tapa_clasificada)
   - [Evento reset](#36-evento-reset)
   - [Consulta db/pull](#37-consulta-dbpull)
   - [Comando gen (SCADA)](#38-comando-gen-scada)
   - [Esquema de base de datos relevante](#39-esquema-de-base-de-datos-relevante)
4. [Flujo completo de una tapa](#4-flujo-completo-de-una-tapa)
5. [Flujo completo de una caja](#5-flujo-completo-de-una-caja)
6. [Configuración](#6-configuración)

---

## 1. Visión general

El sistema automatiza la clasificación de tapas de plástico en una célula de fabricación. Un ESP32-S3 actúa como controlador central: recibe órdenes del SCADA, coordina un robot Delta (clasificador), un robot AMR (transporte), un Cobot (paletizado) y RoboDK (simulación). Cuando una caja se completa, publica un evento MQTT que el puente registra en PostgreSQL.

```
SCADA ──MQTT──► ESP32-S3 ──MQTT──► RoboDK (simulación/spawn)
                    │   ◄──MQTT──── Delta (confirmación clasificación)
                    │   ──MQTT──►  AMR (transporte)
                    │   ──MQTT──►  Cobot (paletizado)
                    │   ──MQTT──►  DB topic
                    │
                    └── mqtt_db_bridge ──► PostgreSQL
```

---

## 2. Firmware ESP32-S3 (prueba2)

### 2.1 Arquitectura de tareas

El firmware ejecuta cuatro tareas concurrentes. La comunicación entre ellas se realiza mediante estado compartido protegido con `Arc<Mutex<ControlState>>` y un `AtomicBool` para la parada de emergencia.

| Tarea | Hilo | Función |
|---|---|---|
| `wifi-manager` | hilo dedicado | Conexión y reconexión Wi-Fi |
| `mqtt-manager` | callback interno del driver | Recepción y despacho de mensajes MQTT |
| `logic-task` | hilo dedicado | Control principal: spawns, coordinación AMR/Cobot, publicación de estado |
| `emergency-task` | hilo principal | Botones físicos, LED y buzzer de emergencia |

El arranque sigue este orden:
1. Inicialización de periféricos y recursos compartidos.
2. Inicio de `wifi-manager` y espera activa hasta que Wi-Fi tenga IP.
3. Carga de conteos de tolvas desde NVS (flash persistente).
4. Conexión MQTT y registro del callback de eventos.
5. Inicio de `logic-task`.
6. El hilo principal entra en `emergency-task` (bucle infinito).

---

### 2.2 Modos de operación

El sistema tiene dos modos seleccionables en tiempo de ejecución:

**Modo Manual**
- Se genera una sola tapa por comando `gen`, con color específico.
- El Delta clasifica la tapa y confirma vía `delta/status` con el color y `id_cap`.
- `manual_remaining` se decrementa al recibir la confirmación del Delta.

**Modo Auto**
- Se genera un lote completo de N tapas con rotación cíclica de los 6 colores válidos.
- El Delta confirma cada tapa; se acepta cualquier color.
- Al completarse el lote (`auto_validated >= auto_target`) se publica un evento `batch_complete` al SCADA.

El modo se cambia con el comando MQTT `set_mode`. Cambiar de modo limpia `id_lote`.

---

### 2.3 Gestión Wi-Fi

**Archivo:** `src/wifi_manager.rs`

- Conexión WPA2 Personal con `ScanMethod::FastScan`.
- Power-save del modem desactivado (`WIFI_PS_NONE`) para evitar desconexiones por inactividad.
- Ante cualquier fallo de conexión: ejecuta `disconnect` → `stop` → espera 2 s → `start` → reintenta. El ciclo `stop/start` limpia el estado interno del driver WiFi.
- La señal `wifi_ready: Arc<AtomicBool>` sincroniza el arranque: el hilo principal espera hasta que sea `true` antes de inicializar MQTT.

---

### 2.4 Gestión MQTT

**Archivo:** `src/mqtt_manager.rs`

- Cliente MQTT síncrono (`EspMqttClient`) con callback de eventos.
- Tras iniciar el cliente espera 5 segundos antes de suscribirse a los topics.
- La suscripción a cada topic se reintenta indefinidamente con backoff de 2 s si falla.
- El callback despacha los mensajes según el topic a funciones especializadas: `handle_delta_status_message`, `handle_amr_status_message`, `handle_cobot_status_message`.
- El método público `publish_text` envía mensajes con QoS `AtLeastOnce`.
- Si el sistema está en emergencia activa, los comandos SCADA `action` se ignoran por completo.

---

### 2.5 Topics MQTT

**Suscritos:**

| Topic | Descripción |
|---|---|
| `giirob/pr2-A1/devices/delta/status` | Confirmaciones de clasificación del robot Delta |
| `giirob/pr2-A1/devices/scada/action` | Comandos de operación del SCADA |
| `giirob/pr2-A1/devices/amr/status` | Reportes de posición del AMR |
| `giirob/pr2-A1/devices/cobot/status` | Reportes de finalización del Cobot |
| `giirob/pr2-A1/system/emergency/action` | Comandos de emergencia remotos |
| `giirob/pr2-A1/db/pull/response` | Respuestas del bridge a consultas de la BD |

**Publicados:**

| Topic | Descripción |
|---|---|
| `giirob/pr2-A1/devices/robodk/action` | Orden SPAWN a RoboDK (generar tapa en simulación) |
| `giirob/pr2-A1/devices/amr/action` | Órdenes de movimiento al AMR |
| `giirob/pr2-A1/devices/cobot/action` | Órdenes de paletizado al Cobot |
| `giirob/pr2-A1/devices/scada/status` | Estado del sistema y eventos hacia el SCADA |
| `giirob/pr2-A1/system/emergency/status` | Cambios de estado de emergencia |
| `giirob/pr2-A1/db/push` | Eventos de caja, paletizado y tapa clasificada para la BD |
| `giirob/pr2-A1/db/pull` | Consultas de datos al bridge (lista de operarios) |

---

### 2.6 Comandos recibidos

#### SCADA action (`giirob/pr2-A1/devices/scada/action`)

**`gen`** — Genera tapas
```json
// Modo Auto
{ "cmd": "gen", "quantity": 100, "id_lote": "L0042" }

// Modo Manual
{ "cmd": "gen", "quantity": 1, "color": "red", "id_lote": "L0042" }
```
- En Auto: establece `auto_target`, reinicia contadores y guarda el `id_lote`.
- En Manual: establece `manual_color`, `manual_spawn_pending = true` y define `expected_tapa`.

**`set_mode`** — Cambia el modo
```json
{ "cmd": "set_mode", "mode": "AUTO" }
{ "cmd": "set_mode", "mode": "MANUAL" }
```

**`status`** — Solicita reporte de estado
```json
{ "cmd": "status" }
```
La respuesta se publica en `giirob/pr2-A1/devices/scada/status` con todos los campos del sistema.

**`reset`** — Reinicia todos los contadores
```json
{ "cmd": "reset" }
```
Limpia tolva_counts, pallet_counts, cobot_next_pallet, estado AMR y Cobot, auto/manual, id_lote, total_processed. Guarda en NVS. Publica evento `reset` al bridge para limpiar la BD.

#### Delta status (`giirob/pr2-A1/devices/delta/status`)

Confirmación de clasificación de una tapa:
```json
{ "status": "completed", "color": "red", "id_cap": "C0005" }
```
- Incrementa `tolva_counts[color]`, `total_processed` y `tapas_clasificadas_pending`.
- En modo Auto: incrementa `auto_validated`; si llega al target, activa `batch_complete_pending`.
- En modo Manual: decrementa `manual_remaining` y limpia `expected_tapa`.
- Guarda `tolva_counts` en NVS.

#### AMR status (`giirob/pr2-A1/devices/amr/status`)

```json
{ "status": "arrived", "location": "TOLVA_1" }
{ "status": "arrived", "location": "cobot_pick" }
```
- Si llega a `tolva_N`: registra `amr_arrived_tolva` y `amr_arrived_at`.
- Si llega a `cobot_pick`: activa `cobot_ready = true`.

#### Cobot status (`giirob/pr2-A1/devices/cobot/status`)

```json
{ "status": "completed", "id_pallet": "P0002" }
```
Activa `cobot_completed_event` y libera `cobot_in_progress`.

#### Emergency action (`giirob/pr2-A1/system/emergency/action`)

```json
{ "cmd": "estop",  "source": "SCADA" }
{ "cmd": "resume", "source": "SCADA" }
```

---

### 2.7 Tarea de lógica

**Archivo:** `src/logic_task.rs`

Bucle principal que corre cada 500 ms:

1. **Spawn de tapas:** si hay tapas pendientes (modo Auto: `auto_spawned < auto_target`; modo Manual: `manual_spawn_pending`), genera un `id_cap` único (formato `C0001`) y publica una orden `spawn` a RoboDK con color e `id_cap`. El Delta recibe la tapa, la clasifica y confirma en `delta/status`.

2. **Procesamiento de Delta:** el callback MQTT actualiza `ControlState` directamente al recibir `delta/status`. La tarea de lógica consume los flags resultantes (`batch_complete_pending`, `tapas_clasificadas_pending`).

3. **Coordinación AMR:** detecta cuándo `tolva_counts[i] >= AMR_TOLVA_THRESHOLD (20)`, genera un `id_caja`, envía `goto tolva_N` y registra `amr_dispatched_at`. Tras 6 s de espera post-llegada (`AMR_ARRIVAL_DELAY_SECS`), envía `goto cobot_pick`, publica `box_completed` a `db/push` y resetea el contador de la tolva en NVS. Timeout: si el AMR no llega en 120 s, se cancela el despacho.

4. **Coordinación Cobot:** cuando `cobot_ready && !cobot_in_progress`, envía `start` al Cobot con el pallet activo del color correspondiente, `boxes_stacked` actual y registra `cobot_started_at`. Timeout: si el Cobot no responde en 60 s, se libera `cobot_in_progress`.

5. **Publicación de estado:** si `status_requested = true`, publica el estado completo al SCADA y limpia el flag.

6. **tapa_clasificada:** si `tapas_clasificadas_pending > 0` y hay `id_lote` activo, publica `{"event":"tapa_clasificada","id_lote":...,"cantidad":N}` a `db/push` en lotes acumulados.

---

### 2.8 Sistema de tolvas

Hay 6 tolvas físicas, cada una asociada a un color de tapa:

| Tolva | Color |
|---|---|
| TOLVA_1 | Rojo (red) |
| TOLVA_2 | Amarillo (yellow) |
| TOLVA_3 | Verde (green) |
| TOLVA_4 | Blanco (white) |
| TOLVA_5 | Naranja (orange) |
| TOLVA_6 | Azul (blue) |

`tolva_counts[i]` se incrementa al recibir `delta/status completed`. El AMR se despacha cuando `tolva_counts[i] >= AMR_TOLVA_THRESHOLD (20)`. Solo puede haber un AMR en tránsito a la vez (`amr_pending_tolva`).

Los conteos se persisten en NVS y sobreviven reinicios.

---

### 2.9 Coordinación AMR

Flujo completo del AMR:

```
tolva_counts[i] >= 20 (AMR_TOLVA_THRESHOLD)
        ↓
ESP32 genera id_caja, registra amr_dispatched_at
publica goto TOLVA_N → AMR
        ↓
AMR publica ARRIVED (location: TOLVA_N)
        ↓
ESP32 registra amr_arrived_tolva, amr_arrived_at
espera 6 segundos (AMR_ARRIVAL_DELAY_SECS)
        ↓
ESP32 publica goto cobot_pick → AMR
ESP32 publica box_completed (id_caja, color, lote) → db/push
tolva_counts[i] = 0  (guardado en NVS)
        ↓
AMR publica ARRIVED (location: cobot_pick)
        ↓
cobot_ready = true
```

Timeout AMR: si no llega en 120 s (`AMR_TIMEOUT_SECS`), se limpian `amr_pending_tolva`, `amr_dispatched_at`, `amr_id_caja` y `amr_caja_tolva`.

---

### 2.10 Coordinación Cobot

El Cobot paletiza cajas procedentes del AMR:

- Hay un pallet activo por cada color (6 en total), indexado igual que las tolvas (`red=0..blue=5`).
- `cobot_next_pallet[i]` es el número del pallet activo para el color `i` (formato `P0001`).
- `pallet_counts[i]` cuenta las cajas en el pallet actual del color `i`.
- Solo se envía una orden al Cobot si no hay otra en progreso (`!cobot_in_progress`).
- Al recibir `completed`:
  1. Se incrementa `pallet_counts[color_index]`.
  2. Si `pallet_counts[i] >= PALLET_CAPACITY (6)`: se cierra el pallet, se solicita operario vía `db/pull`, se publica `caja_paletizada (estado=true, id_operario)` y se notifica `pallet_full` al SCADA. Se reinicia `pallet_counts[i] = 0` y se avanza `cobot_next_pallet[i]`.
  3. Si `pallet_counts[i] < 6`: se publica `caja_paletizada (estado=false)`.
  4. Se libera `cobot_in_progress`.

Timeout Cobot: si no responde en 60 s (`COBOT_TIMEOUT_SECS`), se limpian `cobot_in_progress`, `cobot_started_at`, `cobot_active_color` y `cobot_pending_caja`.

---

### 2.11 Sistema de emergencia

**Archivo:** `src/emergency_task.rs`

- **GPIO38:** botón de emergencia.
- **GPIO39:** botón de reanudación.
- **GPIO10:** LED indicador (encendido = emergencia activa).
- **GPIO48:** buzzer (activo durante emergencia).

Comportamiento:
- Al pulsar emergencia: `emergency_stop = true`, LED y buzzer se activan, publica en `emergency/status`.
- Al pulsar reanudación: `emergency_stop = false`, LED y buzzer se apagan.
- También responde a comandos MQTT `estop`/`resume` en `emergency/action`.
- Cuando `emergency_stop = true`, el callback MQTT ignora todos los comandos SCADA `action`.

---

### 2.12 Persistencia NVS

Los conteos de tolvas se guardan en la partición NVS del flash del ESP32 (namespace `tolva_counts`, claves `tolva_1` a `tolva_6` como `u64`).

- Se cargan al arrancar (si no existen, se usan ceros).
- Se guardan tras cada confirmación del Delta y tras cada recogida del AMR.
- Se borran (ponen a 0 y se guardan) al ejecutar `reset`.
- El namespace se crea automáticamente en el primer arranque (`open_or_create = true`).

---

### 2.13 Estado compartido (ControlState)

**Archivo:** `src/control_state.rs`

Estructura central protegida por `Arc<Mutex<ControlState>>`:

| Campo | Tipo | Descripción |
|---|---|---|
| `mode` | `Mode` | Manual o Auto |
| `auto_target` | `u32` | Tapas totales solicitadas en Auto |
| `auto_spawned` | `u32` | Tapas ya generadas en RoboDK |
| `auto_validated` | `u32` | Tapas confirmadas por Delta en Auto |
| `id_lote` | `Option<String>` | Lote activo |
| `manual_remaining` | `u32` | Tapas manuales pendientes de confirmación |
| `manual_color` | `String` | Color esperado en modo Manual |
| `manual_spawn_pending` | `bool` | Flag para generar la siguiente tapa manual |
| `expected_tapa` | `Option<ExpectedTapa>` | Color esperado de la próxima tapa |
| `total_processed` | `u64` | Total de tapas procesadas (se resetea con `reset`) |
| `tolva_counts` | `[u64; 6]` | Tapas confirmadas por tolva (red=0..blue=5) |
| `amr_pending_tolva` | `Option<usize>` | Tolva a la que se dirigió el AMR |
| `amr_dispatched_at` | `Option<Instant>` | Momento de despacho del AMR (para timeout) |
| `amr_arrived_tolva` | `Option<usize>` | Tolva donde llegó el AMR |
| `amr_arrived_at` | `Option<Instant>` | Momento de llegada del AMR a la tolva |
| `amr_id_caja` | `Option<String>` | ID de la caja que transporta el AMR |
| `amr_caja_tolva` | `Option<usize>` | Tolva de origen de la caja |
| `cobot_ready` | `bool` | AMR llegó a cobot_pick con caja lista |
| `cobot_in_progress` | `bool` | Cobot ejecutando una operación |
| `cobot_started_at` | `Option<Instant>` | Momento de inicio del Cobot (para timeout) |
| `cobot_next_pallet` | `[u32; 6]` | Número del pallet activo por color |
| `cobot_pending_color` | `Option<String>` | Color de la caja que espera el Cobot |
| `cobot_pending_caja` | `Option<String>` | ID de la caja que espera el Cobot |
| `cobot_active_color` | `Option<String>` | Color de la operación en curso |
| `cobot_completed_event` | `Option<String>` | id_pallet del último completed del Cobot |
| `pallet_counts` | `[u64; 6]` | Cajas en el pallet actual por color |
| `status_requested` | `bool` | Solicitud de estado pendiente |
| `batch_complete_pending` | `bool` | Lote Auto completado, pendiente de publicar |
| `reset_db_pending` | `bool` | Reset pendiente de publicar al bridge |
| `tapas_clasificadas_pending` | `u32` | Tapas clasificadas pendientes de publicar a BD |

---

## 3. Puente MQTT-PostgreSQL (mqtt_db_bridge)

### 3.1 Función

Servicio Rust asíncrono (`tokio`) que actúa como puente entre el broker MQTT y una base de datos PostgreSQL. Escucha eventos y comandos en tiempo real y los persiste de forma fiable.

Tecnologías: `rumqttc` (cliente MQTT async), `tokio-postgres` (cliente PostgreSQL async), `tracing` (logging estructurado).

Las sentencias SQL se preparan una sola vez al arrancar para máximo rendimiento.

---

### 3.2 Topics escuchados

| Topic | Tipo de mensaje |
|---|---|
| `giirob/pr2-A1/db/push` | Eventos de escritura: box_completed, caja_paletizada, tapa_clasificada, reset |
| `giirob/pr2-A1/db/pull` | Consultas de datos (operarios) |
| `giirob/pr2-A1/devices/scada/action` | Comandos de generación de lotes (`gen`) |

---

### 3.3 Evento box_completed

**Topic:** `giirob/pr2-A1/db/push`

```json
{
  "event": "box_completed",
  "id_caja": "B0001",
  "color": "red",
  "codigo_etiqueta": "ETQ0000001",
  "estado": true,
  "lotes": ["L0042"]
}
```

**Acciones:**
1. Normaliza el color a mayúsculas.
2. Upsert en `caja` (ON CONFLICT actualiza `color`, `codigo_etiqueta`, `estado`; no modifica `id_palet`).
3. Para cada elemento del array `lotes`, inserta en `material_caja` (ON CONFLICT DO NOTHING).

---

### 3.4 Evento caja_paletizada

**Topic:** `giirob/pr2-A1/db/push`

```json
{ "event": "caja_paletizada", "id_caja": "B0001", "id_palet": "P0001", "id_color": "RED", "estado": false }
```

Con cierre de pallet (`estado: true`):
```json
{ "event": "caja_paletizada", "id_caja": "B0012", "id_palet": "P0001", "id_color": "RED", "estado": true, "id_operario": "OP003" }
```

**Acciones:**
1. Upsert en `palet (id_palet, id_color, estado)`.
2. `UPDATE caja SET id_palet = $id_palet WHERE id_caja = $id_caja`.
3. Si `estado = true` y hay `id_operario`: `UPDATE palet SET id_operario = $id_operario`.

---

### 3.5 Evento tapa_clasificada

**Topic:** `giirob/pr2-A1/db/push`

```json
{ "event": "tapa_clasificada", "id_lote": "L0042", "cantidad": 5 }
```

**Acción:** `UPDATE lote SET total_tapas_clasificadas = LEAST(total_tapas_clasificadas + cantidad, total_tapas_entrada) WHERE id_lote = $id_lote`

El LEAST garantiza que `total_tapas_clasificadas` nunca supere `total_tapas_entrada`.

---

### 3.6 Evento reset

**Topic:** `giirob/pr2-A1/db/push`

```json
{ "event": "reset", "device": "ESP32-S3" }
```

**Acciones (en orden):** `DELETE FROM material_caja` → `DELETE FROM caja` → `DELETE FROM palet`.

---

### 3.7 Consulta db/pull

**Request** (`giirob/pr2-A1/db/pull`):
```json
{ "query": "operarios" }
```

**Response** (`giirob/pr2-A1/db/pull/response`):
```json
{ "operarios": [{"id_operario":"OP001","nombre":"Carlos","apellido":"Martínez"}, ...] }
```

---

### 3.8 Comando gen (SCADA)

**Topic:** `giirob/pr2-A1/devices/scada/action`

```json
{ "cmd": "gen", "id_lote": "L0042", "proveedor": "P0003", "quantity": 500 }
```

**Acciones:**
1. Inserta en `lote` con `fecha_inicio = CURRENT_DATE`, `total_tapas_clasificadas = 0`. ON CONFLICT DO NOTHING.
2. Si `proveedor` no está vacío, inserta en `proveedor_material`. ON CONFLICT DO NOTHING.

---

### 3.9 Esquema de base de datos relevante

```sql
lote (
    id_lote                  CHAR(5) PRIMARY KEY,
    fecha_inicio             DATE NOT NULL,
    fecha_fin                DATE,
    total_tapas_entrada      INT NOT NULL,
    total_tapas_clasificadas INT NOT NULL DEFAULT 0,
    observaciones            VARCHAR(200)
)

caja (
    id_caja         CHAR(5) PRIMARY KEY,
    color           VARCHAR(20) NOT NULL,   -- RED, GREEN, BLUE, YELLOW, ORANGE, WHITE
    codigo_etiqueta CHAR(10) NOT NULL,
    estado          BOOLEAN NOT NULL,
    id_palet        CHAR(5)
)

material_caja (
    lote    CHAR(5),
    id_caja CHAR(5),
    PRIMARY KEY (lote, id_caja)
)

palet (
    id_palet    CHAR(5) PRIMARY KEY,
    id_color    CHAR(20),
    estado      BOOL,
    id_operario CHAR(5)
)
```

---

## 4. Flujo completo de una tapa

```
SCADA envía gen (color=red, modo Manual)
    │
    ▼
ESP32: manual_spawn_pending = true, expected_tapa = {color: "red"}
    │
    ▼
logic-task detecta pending → genera id_cap="C0001"
publica spawn (color=red, id_cap=C0001) → RoboDK
    │
    ▼
RoboDK genera tapa, Delta la clasifica físicamente en TOLVA_1
Delta publica completed (status=completed, color=red, id_cap=C0001) → delta/status
    │
    ▼
ESP32 recibe → tolva_counts[0]++, total_processed++
tapas_clasificadas_pending++ (si hay id_lote activo)
manual_remaining--, expected_tapa = None
guarda NVS
```

---

## 5. Flujo completo de una caja

```
tolva_counts[0] >= 20  (TOLVA_1 tiene 20 tapas: red)
    │
    ▼
logic-task detecta umbral → amr_pending_tolva = 0, amr_dispatched_at = now()
ESP32 genera id_caja="B0001"
publica goto TOLVA_1 → AMR
    │
    ▼
AMR llega a TOLVA_1 → publica ARRIVED (location=TOLVA_1)
    │
    ▼
ESP32: amr_arrived_tolva = 0, amr_arrived_at = now()
    │
    ▼ (después de 6 segundos)
logic-task detecta delay cumplido:
  tolva_counts[0] = 0  (guardado en NVS)
  publica goto cobot_pick → AMR
  publica box_completed (id_caja=B0001, color=red, lote=L0042) → db/push
    │
    ├──► bridge inserta caja B0001 en PostgreSQL
    │    bridge inserta material_caja (L0042, B0001)
    │
    ▼
AMR llega a cobot_pick → publica ARRIVED (location=cobot_pick)
    │
    ▼
ESP32: cobot_ready = true
    │
    ▼
logic-task: publica start (id_pallet=P0001, color=red, boxes_stacked=0) → Cobot
cobot_in_progress = true, cobot_started_at = now()
    │
    ▼
Cobot paletiza → publica completed (id_pallet=P0001)
    │
    ▼
ESP32: pallet_counts[0]++ (red)
    │
    ├── Si pallet_counts[0] >= 6 (PALLET_CAPACITY):
    │       ESP32 solicita operario → db/pull
    │       Bridge responde con lista de operarios
    │       ESP32 escoge id_operario
    │       publica caja_paletizada (estado=true, id_operario=OP003) → db/push
    │       publica pallet_full (id_palet=P0001, color=red) → scada/status
    │       pallet_counts[0] = 0, cobot_next_pallet[0]++
    │
    └── Si pallet_counts[0] < 6:
            publica caja_paletizada (estado=false) → db/push
    │
    ▼
bridge: upsert palet, vincula caja, asigna operario si aplica
cobot_in_progress = false
```

---

## 6. Configuración

### Firmware (`src/config.rs`)

| Constante | Valor | Descripción |
|---|---|---|
| `WIFI_SSID` | `"HUAWEI-2.4G-pXj3"` | Red Wi-Fi |
| `MQTT_URL` | `"mqtt://broker.hivemq.com:1883"` | Broker MQTT |
| `MQTT_CLIENT_ID` | `"ESP32_PR2A1"` | ID del cliente MQTT |
| `AMR_TOLVA_THRESHOLD` | `20` | Tapas para despachar AMR (1 caja llena) |
| `AMR_ARRIVAL_DELAY_SECS` | `6` | Segundos de espera tras llegada del AMR a la tolva |
| `AMR_WAREHOUSE_LOCATION` | `"cobot_pick"` | Ubicación del área del Cobot |
| `AMR_TIMEOUT_SECS` | `120` | Timeout de espera para el AMR |
| `COBOT_PALLET_ID_BASE` | `1` | Número del primer pallet (`P0001`) |
| `PALLET_CAPACITY` | `6` | Cajas por pallet (2 cajas/nivel × 3 niveles) |
| `COBOT_TIMEOUT_SECS` | `60` | Timeout de espera para el Cobot |
| `VALID_COLORS` | `["red","green","yellow","blue","white","orange"]` | Colores aceptados |

### Bridge (`mqtt_db_bridge/.env`)

| Variable | Descripción |
|---|---|
| `MQTT_HOST` | Host del broker MQTT |
| `MQTT_PORT` | Puerto del broker (por defecto 1883) |
| `MQTT_CLIENT_ID` | ID del cliente MQTT del bridge |
| `DATABASE_URL` | Cadena de conexión PostgreSQL |
