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
   - [Tarea de visión](#27-tarea-de-visión)
   - [Tarea de lógica](#28-tarea-de-lógica)
   - [Sistema de tolvas](#29-sistema-de-tolvas)
   - [Coordinación AMR](#210-coordinación-amr)
   - [Coordinación Cobot](#211-coordinación-cobot)
   - [Sistema de emergencia](#212-sistema-de-emergencia)
   - [Persistencia NVS](#213-persistencia-nvs)
   - [Estado compartido (ControlState)](#214-estado-compartido-controlstate)
3. [Puente MQTT-PostgreSQL (mqtt_db_bridge)](#3-puente-mqtt-postgresql-mqtt_db_bridge)
   - [Función](#31-función)
   - [Topics escuchados](#32-topics-escuchados)
   - [Evento BOX_COMPLETED](#33-evento-box_completed)
   - [Comando gen (SCADA)](#34-comando-gen-scada)
   - [Esquema de base de datos relevante](#35-esquema-de-base-de-datos-relevante)
4. [Flujo completo de una tapa](#4-flujo-completo-de-una-tapa)
5. [Flujo completo de una caja](#5-flujo-completo-de-una-caja)
6. [Configuración](#6-configuración)

---

## 1. Visión general

El sistema automatiza la clasificación de tapas de plástico en una célula de fabricación. Un ESP32-S3 actúa como controlador central: recibe órdenes del SCADA, coordina un robot Delta (clasificador), un robot AMR (transporte), un Cobot (paletizado) y una cámara de visión artificial. Cuando una caja se completa, publica un evento MQTT que el puente registra en PostgreSQL.

```
SCADA ──MQTT──► ESP32-S3 ──MQTT──► Delta (clasificador)
                    │   ◄──MQTT──── Cámara (visión)
                    │   ──MQTT──►  AMR (transporte)
                    │   ──MQTT──►  Cobot (paletizado)
                    │   ──MQTT──►  RoboDK (simulación)
                    │   ──MQTT──►  DB topic
                    │
                    └── mqtt_db_bridge ──► PostgreSQL
```

---

## 2. Firmware ESP32-S3 (prueba2)

### 2.1 Arquitectura de tareas

El firmware ejecuta cuatro tareas concurrentes. La comunicación entre ellas se realiza mediante canales (`sync_channel`) y estado compartido protegido con `Mutex`.

| Tarea | Hilo | Función |
|---|---|---|
| `wifi-manager` | hilo dedicado (Core 0) | Conexión y reconexión Wi-Fi |
| `mqtt-manager` | callback interno del driver | Recepción y despacho de mensajes MQTT |
| `vision-task` | hilo dedicado | Filtrado de detecciones de cámara |
| `logic-task` | hilo dedicado | Control principal: spawns, validaciones, coordinación |
| `emergency-task` | hilo principal | Botones físicos, LED y buzzer de emergencia |

El arranque sigue este orden:
1. Inicialización de periféricos y recursos compartidos.
2. Inicio de `wifi-manager` y espera activa hasta que Wi-Fi tenga IP.
3. Carga de conteos de tolvas desde NVS (flash persistente).
4. Conexión MQTT y registro del callback de eventos.
5. Inicio de `vision-task` y `logic-task`.
6. El hilo principal entra en `emergency-task` (bucle infinito).

---

### 2.2 Modos de operación

El sistema tiene dos modos seleccionables en tiempo de ejecución:

**Modo Manual**
- Se genera una sola tapa por comando, con color específico.
- La lógica valida que la tapa detectada por la cámara coincida exactamente con el color solicitado antes de enviar la orden PICK al Delta.
- Si el color no coincide, la tapa se descarta (no se envía PICK).

**Modo Auto**
- Se genera un lote completo de N tapas (cualquier color, rotación cíclica por los 6 colores válidos).
- La cámara valida cada tapa detectada; se acepta cualquier color.
- Al completarse el lote (`auto_validated >= auto_target`) se publica un evento `batch_complete` al topic de estado del SCADA.

El modo se cambia con el comando MQTT `set_mode`.

---

### 2.3 Gestión Wi-Fi

**Archivo:** `src/wifi_connection.rs`, `src/wifi_manager.rs`

- Conexión WPA2 Personal con `ScanMethod::FastScan` (escaneo de canal activo en lugar de todos los canales, reduce el tiempo de asociación).
- Power-save del modem desactivado (`WIFI_PS_NONE`) para evitar desconexiones por inactividad.
- Ante cualquier fallo de conexión (timeout, deautenticación del AP): ejecuta `disconnect` → `stop` → espera 2 s → `start` → reintenta `connect`. El ciclo `stop/start` limpia el estado interno del driver WiFi del ESP32.
- El monitor de `run_wifi_manager` comprueba la conexión cada 3 segundos; si detecta desconexión llama a `reconnect_wifi`, que aplica el mismo ciclo de reset.
- La señal `wifi_ready: Arc<AtomicBool>` sincroniza el arranque: el hilo principal espera hasta que sea `true` antes de inicializar MQTT.

---

### 2.4 Gestión MQTT

**Archivo:** `src/mqtt_manager.rs`

- Cliente MQTT síncrono (`EspMqttClient`) con callback de eventos.
- Tras iniciar el cliente espera 5 segundos antes de suscribirse a los topics, para asegurar que la conexión al broker esté estabilizada.
- La suscripción a cada topic se reintenta indefinidamente con backoff de 2 s si falla.
- El callback despacha los mensajes según el topic recibido a funciones especializadas (`handle_scada_status_message`, `handle_amr_status_message`, `handle_cobot_status_message`).
- El método público `publish_text` envía mensajes con QoS `AtLeastOnce`.
- Si el sistema está en emergencia activa, los comandos SCADA `action` se ignoran por completo.

---

### 2.5 Topics MQTT

**Suscritos:**

| Topic | Descripción |
|---|---|
| `giirob/pr2-A1/devices/camera/data` | Detecciones de la cámara de visión |
| `giirob/pr2-A1/devices/scada/action` | Comandos de operación del SCADA |
| `giirob/pr2-A1/devices/scada/status` | Confirmaciones de entrega del SCADA |
| `giirob/pr2-A1/devices/amr/status` | Reportes de posición del AMR |
| `giirob/pr2-A1/devices/cobot/status` | Reportes de finalización del Cobot |
| `giirob/pr2-A1/system/emergency/action` | Comandos de emergencia remotos |

**Publicados:**

| Topic | Descripción |
|---|---|
| `giirob/pr2-A1/devices/robodk/action` | Orden SPAWN a RoboDK (generar tapa en simulación, incluye id_cap) |
| `giirob/pr2-A1/devices/delta/action` | Orden PICK al robot Delta |
| `giirob/pr2-A1/devices/amr/action` | Órdenes de movimiento al AMR |
| `giirob/pr2-A1/devices/cobot/action` | Órdenes de paletizado al Cobot |
| `giirob/pr2-A1/devices/scada/status` | Estado del sistema hacia el SCADA |
| `giirob/pr2-A1/system/emergency/status` | Cambios de estado de emergencia |
| `giirob/pr2-A1/db/push` | Eventos de caja completada y paletizado para la base de datos |
| `giirob/pr2-A1/db/pull` | Consultas de datos al bridge (ej: lista de operarios) |

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
- En Manual: establece `manual_color`, `manual_spawn_pending = true` y define el color esperado.

**`set_mode`** — Cambia el modo
```json
{ "cmd": "set_mode", "mode": "AUTO" }
{ "cmd": "set_mode", "mode": "MANUAL" }
```

**`status`** — Solicita reporte de estado
```json
{ "cmd": "status" }
```
La respuesta se publica en `giirob/pr2-A1/devices/scada/status` con campos: modo, id_lote, totales de auto y manual, colores esperados, estado del AMR, conteos de tolvas y pallets.

**`reset`** — Reinicia todos los contadores
```json
{ "cmd": "reset" }
```
Limpia tolva_counts, pending_tolva_counts, pending_tapas, estado AMR y Cobot, auto_target/spawned/validated y id_lote. Guarda en NVS.

#### SCADA status (`giirob/pr2-A1/devices/scada/status`)

Confirmación de entrega de una tapa a una tolva:
```json
{ "cmd": "done", "id_cap": "C0005", "tolva": "TOLVA_3" }
```
- Valida que el `id_cap` estaba pendiente y que la tolva coincide.
- Transfiere el conteo de `pending_tolva_counts` a `tolva_counts` y guarda en NVS.
- Si la tolva no coincide con la esperada, registra el error pero reinserta el `id_cap` como pendiente.

#### AMR status (`giirob/pr2-A1/devices/amr/status`)

**Llegada a posición (case 2):**
```json
{ "status": "arrived", "location": "TOLVA_1" }
{ "status": "arrived", "location": "cobot_pick" }
```
- Si llega a `tolva_N`: registra la llegada (`amr_arrived_tolva`, `amr_arrived_at`).
- Si llega a `cobot_pick`: activa `cobot_ready = true`.

**Estado de operación hacia el SCADA (case 3):**
```json
{ "status": "active",   "location": "TOLVA_1" }
{ "status": "inactive", "location": "TOLVA_1" }
```
El ESP32 ignora estos mensajes; son informativos para el SCADA.

#### Cobot status (`giirob/pr2-A1/devices/cobot/status`)

```json
{ "status": "completed", "id_pallet": "P0002" }
```
Incrementa `pallet_counts[id_pallet - COBOT_PALLET_ID_BASE]` y libera `cobot_in_progress`.

#### Emergency action (`giirob/pr2-A1/system/emergency/action`)

Comandos remotos de emergencia recibidos por el ESP32. Todos los dispositivos incluyen `source`:
```json
{ "cmd": "estop",  "source": "SCADA"                        }
{ "cmd": "resume", "source": "SCADA"                        }
{ "cmd": "estop",  "source": "AMR",   "reason": "collision" }
{ "cmd": "estop",  "source": "COBOT", "reason": "joint_limit" }
{ "cmd": "estop",  "source": "DELTA"                        }
```

#### Emergency status recibido por el AMR (`giirob/pr2-A1/system/emergency/status`)

El ESP32 publica en este topic cuando activa o desactiva la emergencia. El AMR se suscribe para detenerse o reanudarse:

**Emergencia activa (case 4):**
```json
{ "status": "emergency_active",   "source": "emergency_button" }
{ "status": "emergency_active",   "source": "AMR"              }
```

**Emergencia resuelta (case 5):**
```json
{ "status": "emergency_inactive", "source": "resume_button" }
{ "status": "emergency_inactive", "source": "SCADA"         }
```

---

### 2.7 Tarea de visión

**Archivo:** `src/vision_task.rs`

Hilo dedicado que consume mensajes crudos de la cámara del canal interno:

1. Deserializa el JSON recibido.
2. Descarta detecciones con `precision <= 0.95`.
3. Extrae `x`, `y`, `color` y `id_cap`. El `id_cap` lo genera el ESP32 en el spawn y RoboDK lo incluye en el mensaje de cámara, por lo que siempre está presente.
4. Envía el `VisionSample` al canal de `logic-task`.

Formato de entrada esperado (topic `camera/data`):
```json
{
  "x": 123.4,
  "y": 56.7,
  "color": "red",
  "precision": 0.97,
  "id_cap": "C0042"
}
```

---

### 2.8 Tarea de lógica

**Archivo:** `src/logic_task.rs`

Bucle principal que corre cada 500 ms o en cada detección de cámara:

1. **Spawn de tapas:** si hay tapas pendientes de generar (modo Auto o Manual con `manual_spawn_pending`), genera un `id_cap` único (ej. `C0042`) y publica una orden `SPAWN` a RoboDK con el color y el `id_cap`. En Auto, el color rota cíclicamente entre los 6 válidos. El `id_cap` se genera aquí para que el ESP32 conozca el identificador de la tapa desde el momento del spawn, antes de recibir la detección de cámara.

2. **Procesamiento de visión:** al recibir un `VisionSample`:
   - Valida el color según el modo (Manual: debe coincidir; Auto: cualquier color).
   - Mapea el color a una tolva (`red→0, yellow→1, green→2, white→3, orange→4, blue→5`).
   - **Comprueba que la tolva no esté llena** (`tolva_counts[idx] + pending_tolva_counts[idx] >= AMR_TOLVA_THRESHOLD`). Si está llena, la tapa se rechaza y no se envía PICK, evitando el rebalsamiento físico.
   - Si la tolva tiene espacio, publica una orden `PICK` al Delta con coordenadas `x`, `y`, `color`, `tolva` y `id_cap`.
   - Registra el `id_cap` como pendiente en `pending_tapas`.
   - En Auto, al completar el lote, publica `batch_complete` al SCADA.

3. **Coordinación AMR:** detecta cuándo una tolva supera el umbral (`AMR_TOLVA_THRESHOLD = 2`) y envía `goto tolva_N` al AMR. Después del tiempo de espera post-llegada (`AMR_ARRIVAL_DELAY_SECS = 10 s`), envía el AMR a `cobot_pick` y simultáneamente publica el evento `BOX_COMPLETED` con la caja y el lote activo.

4. **Coordinación Cobot:** cuando `cobot_ready && !cobot_in_progress`, envía una orden `start` al Cobot con el siguiente pallet en rotación (6 pallets, IDs de P0001 a P0006).

5. **Publicación de estado:** si `status_requested = true`, publica el estado completo y limpia el flag.

---

### 2.9 Sistema de tolvas

Hay 6 tolvas físicas, cada una asociada a un color de tapa:

| Tolva | Color |
|---|---|
| TOLVA_1 | Rojo |
| TOLVA_2 | Amarillo |
| TOLVA_3 | Verde |
| TOLVA_4 | Blanco |
| TOLVA_5 | Naranja |
| TOLVA_6 | Azul |

Cada tolva tiene dos contadores:
- `tolva_counts[i]`: tapas confirmadas por el SCADA como entregadas.
- `pending_tolva_counts[i]`: tapas en tránsito (PICK enviado, confirmación pendiente).

El AMR se despacha cuando `tolva_counts[i] >= AMR_TOLVA_THRESHOLD (2)`.

**Protección contra rebalsamiento:** antes de enviar cualquier PICK al Delta, la lógica comprueba que `tolva_counts[i] + pending_tolva_counts[i] < AMR_TOLVA_THRESHOLD`. Si la suma ya alcanza el umbral (incluyendo tapas en tránsito), la tapa se rechaza sin enviar PICK. Esto impide que el Delta siga depositando tapas en una tolva que ya está al límite físico mientras el AMR todavía no ha llegado a recogerla.

El umbral y el delay post-llegada son configurables en `config.rs`.

---

### 2.10 Coordinación AMR

Flujo completo del AMR:

```
tolva_counts[i] >= umbral
        ↓
ESP32 genera id_caja, guarda en amr_id_caja
publica goto tolva_N → AMR
        ↓
AMR publica ARRIVED (location: tolva_N)
        ↓
ESP32 registra amr_arrived_tolva, amr_arrived_at
espera 10 segundos
        ↓
ESP32 publica goto cobot_pick → AMR
ESP32 publica BOX_COMPLETED (id_caja=amr_id_caja, ...) → db/push
tolva_counts[i] = 0
        ↓
AMR publica ARRIVED (location: cobot_pick)
        ↓
cobot_ready = true
```

Solo puede haber un AMR en tránsito a la vez (`amr_pending_tolva`). Si llega a una tolva distinta de la esperada, se registra el error pero no se interrumpe el flujo.

---

### 2.11 Coordinación Cobot

El Cobot paletiza cajas procedentes del AMR:

- Usa 6 pallets con IDs de P0001 a P0015 (`COBOT_PALLET_ID_BASE = 1`, `COBOT_PALLET_COUNT = 6`).
- La posición física se designa como `pallet1` a `pallet6`.
- El índice de pallet activo rota cíclicamente con cada operación.
- Solo se envía una orden al Cobot si no hay otra en progreso (`!cobot_in_progress`).
- Al recibir `completed`:
  1. Se incrementa `pallet_counts[index]`.
  2. Antes de publicar `caja_paletizada`, si `estado:true` el ESP32 solicita la lista de operarios vía `db/pull` (`{"query":"operarios"}`), espera la respuesta en `db/pull/response`, escoge uno y lo incluye como `id_operario`. Luego publica `caja_paletizada` al topic `db/push`.
  3. Si `pallet_counts[index] >= PALLET_CAPACITY` (12 cajas): se publica `pallet_full` al SCADA para avisar al operario y se reinicia `pallet_counts[index] = 0`.
  4. Se libera el flag `cobot_in_progress`.

---

### 2.12 Sistema de emergencia

**Archivo:** `src/emergency_task.rs`

Corre en el hilo principal mediante interrupciones de hardware:

- **GPIO38:** botón de emergencia (activo en flanco descendente).
- **GPIO39:** botón de reanudación.
- **GPIO10:** LED indicador (encendido = emergencia activa).
- **GPIO11:** buzzer (activo durante emergencia).

Comportamiento:
- Al pulsar emergencia: `emergency_stop = true`, LED y buzzer se activan, se publica en `emergency/status`:
  ```json
  { "status": "emergency_active", "source": "emergency_button" }
  ```
- Al pulsar reanudación: `emergency_stop = false`, LED y buzzer se apagan, se publica:
  ```json
  { "status": "emergency_inactive", "source": "resume_button" }
  ```
- También responde a comandos MQTT `estop`/`resume` en `emergency/action`.
- Cuando `emergency_stop = true`, el callback MQTT ignora todos los comandos SCADA `action`.

Las interrupciones se re-suscriben en cada iteración del bucle (50 ms de timeout de espera), patrón necesario para el modelo de ISR de esp-idf-svc.

---

### 2.13 Persistencia NVS

Los conteos de tolvas se guardan en la partición NVS del flash del ESP32 (namespace `tolva_counts`, claves `tolva_1` a `tolva_6` como `u64`).

- Se cargan al arrancar (si no existen, se usan ceros con un warning).
- Se guardan tras cada confirmación del SCADA y tras cada `reset`.
- Esto garantiza que los conteos sobreviven reinicios y cortes de luz.

---

### 2.14 Estado compartido (ControlState)

**Archivo:** `src/control_state.rs`

Estructura central protegida por `Arc<Mutex<ControlState>>`, accesible desde todas las tareas:

| Campo | Tipo | Descripción |
|---|---|---|
| `mode` | `Mode` | Manual o Auto |
| `auto_target` | `u32` | Tapas totales solicitadas en Auto |
| `auto_spawned` | `u32` | Tapas ya generadas en RoboDK |
| `auto_validated` | `u32` | Tapas validadas por la cámara |
| `id_lote` | `Option<String>` | Lote activo (se incluye en BOX_COMPLETED) |
| `manual_remaining` | `u32` | Tapas manuales pendientes |
| `manual_color` | `String` | Color esperado en modo manual |
| `manual_spawn_pending` | `bool` | Flag para generar la siguiente tapa manual |
| `expected_tapa` | `Option<ExpectedTapa>` | Color y estado de validación esperado |
| `total_processed` | `u64` | Total de tapas procesadas en la sesión |
| `tolva_counts` | `[u64; 6]` | Tapas confirmadas por tolva |
| `pending_tolva_counts` | `[u64; 6]` | Tapas en tránsito por tolva |
| `pending_tapas` | `HashMap<String, usize>` | id_cap → índice de tolva esperado |
| `amr_pending_tolva` | `Option<usize>` | Tolva a la que se dirigió el AMR |
| `amr_arrived_tolva` | `Option<usize>` | Tolva donde llegó el AMR |
| `amr_arrived_at` | `Option<Instant>` | Momento de llegada del AMR |
| `amr_id_caja` | `Option<String>` | ID de la caja que transporta el AMR |
| `amr_caja_tolva` | `Option<usize>` | Tolva de origen de la caja |
| `cobot_ready` | `bool` | AMR llegó a cobot_pick |
| `cobot_in_progress` | `bool` | Cobot ejecutando una operación |
| `cobot_next_pallet` | `usize` | Índice del siguiente pallet a usar |
| `pallet_counts` | `[u64; 6]` | Cajas paletizadas por pallet |
| `status_requested` | `bool` | Solicitud de estado pendiente |

---

## 3. Puente MQTT-PostgreSQL (mqtt_db_bridge)

### 3.1 Función

Servicio Rust asíncrono (`tokio`) que actúa como puente entre el broker MQTT y una base de datos PostgreSQL. Escucha eventos y comandos en tiempo real y los persiste de forma fiable.

Tecnologías: `rumqttc` (cliente MQTT async), `tokio-postgres` (cliente PostgreSQL async), `tracing` (logging estructurado).

Las sentencias SQL se preparan una sola vez al arrancar (`pg.prepare(...)`) para máximo rendimiento.

**Arquitectura interna:** el parsing de los mensajes JSON está separado del loop principal en funciones puras con structs tipados de salida:

```rust
struct BoxCompletedEvent   { id_caja, color_db, etiqueta, estado, lotes }
struct GenCommand          { proveedor: Option<String>, id_lote, quantity }
struct CajaPaletizadaEvent { id_caja, id_palet, id_color, estado, id_operario: Option<String> }

fn parse_box_completed_event(value: &Value) -> Option<BoxCompletedEvent>
fn parse_gen_command(value: &Value)         -> Option<GenCommand>
fn parse_caja_paletizada(value: &Value)     -> Option<CajaPaletizadaEvent>
```

Esto permite verificar el parsing con tests unitarios sin necesitar MQTT ni base de datos. El módulo `#[cfg(test)]` cubre 6 casos: normalización de color y lotes, valor por defecto de `estado`, campos requeridos vacíos, alias `lote`/`id_lote` (compatibilidad), `proveedor` opcional y `quantity ≤ 0`.

---

### 3.2 Topics escuchados

| Topic | Tipo de mensaje |
|---|---|
| `giirob/pr2-A1/db/push` | Escritura: eventos de caja completada y paletizado |
| `giirob/pr2-A1/db/pull` | Lectura: consultas de datos de la BD (ej: operarios) |
| `giirob/pr2-A1/devices/scada/action` | Comandos de generación de lotes |

---

### 3.3 Evento BOX_COMPLETED

**Topic:** `giirob/pr2-A1/db/push`

```json
{
  "event": "BOX_COMPLETED",
  "id_caja": "B0001",
  "color": "RED",
  "codigo_etiqueta": "ETQ0000001",
  "estado": true,
  "lotes": ["L0042"]
}
```

**Acciones:**
1. Normaliza el color a mayúsculas (`to_ascii_uppercase`).
2. Inserta o actualiza la tabla `caja` (ON CONFLICT actualiza `color`, `codigo_etiqueta`, `estado`; **no modifica `id_palet`**).
3. Para cada elemento del array `lotes`, inserta en `material_caja (lote, id_caja)` (ON CONFLICT DO NOTHING).

Campos requeridos: `id_caja`, `color`, `codigo_etiqueta`. Si alguno falta, se descarta el mensaje con un warning.

### 3.4b Evento CAJA_PALETIZADA

**Topic:** `giirob/pr2-A1/db/push`

```json
{
  "event": "caja_paletizada",
  "id_caja": "B0001",
  "id_palet": "P0001",
  "id_color": "RED",
  "estado": false
}
```

Con cierre de pallet (`estado: true`), incluye además el `id_operario` elegido por el ESP32:
```json
{
  "event": "caja_paletizada",
  "id_caja": "B0012",
  "id_palet": "P0001",
  "id_color": "RED",
  "estado": true,
  "id_operario": "OP003"
}
```

**Acciones:**
1. Upsert en `palet (id_palet, id_color, estado)` — ON CONFLICT actualiza `estado`.
2. `UPDATE caja SET id_palet = $id_palet WHERE id_caja = $id_caja`.
3. Si `estado = true` y se recibe `id_operario`: `UPDATE palet SET id_operario = $id_operario WHERE id_palet = $id_palet`.

### 3.4c Consulta db/pull

El ESP32 solicita datos a la BD antes de tomar decisiones. Patrón request-response:

**Request** (`giirob/pr2-A1/db/pull`):
```json
{ "query": "operarios" }
```

**Response** (`giirob/pr2-A1/db/pull/response`):
```json
{ "operarios": [{"id_operario":"OP001","nombre":"Carlos","apellido":"Martínez"}, ...] }
```

El bridge consulta `SELECT id_operario, nombre, apellido FROM operario` y publica el resultado. El ESP32 escoge un operario y lo incluye en el siguiente evento `caja_paletizada`.

---

### 3.4 Comando gen (SCADA)

**Topic:** `giirob/pr2-A1/devices/scada/action`

```json
{
  "cmd": "gen",
  "id_lote": "L0042",
  "proveedor": "P0003",
  "quantity": 500
}
```

**Acciones:**
1. Inserta en `lote` con `fecha_inicio = CURRENT_DATE`, `fecha_fin = NULL` (lote abierto), `total_tapas_clasificadas = 0`. ON CONFLICT DO NOTHING (un lote duplicado se ignora silenciosamente).
2. Si se proporciona `proveedor` (no vacío), inserta en `proveedor_material (proveedor, lote)`. ON CONFLICT DO NOTHING.

Acepta tanto `id_lote` como `lote` como nombre del campo. El `quantity` se convierte de `i64` a `i32` para compatibilidad con la columna `INT` de PostgreSQL.

Campos requeridos: `id_lote` (o `lote`) y `quantity > 0`. Si faltan o son inválidos, se descarta con warning.

---

### 3.5 Esquema de base de datos relevante

```sql
-- Lotes de tapas sin clasificar
lote (
    id_lote                  CHAR(5) PRIMARY KEY,  -- ej: L0042
    fecha_inicio             DATE NOT NULL,
    fecha_fin                DATE,                  -- NULL mientras el lote está activo
    total_tapas_entrada      INT NOT NULL,
    total_tapas_clasificadas INT NOT NULL DEFAULT 0,
    observaciones            VARCHAR(200)
)

-- Cajas de tapas clasificadas
caja (
    id_caja         CHAR(5) PRIMARY KEY,            -- ej: B0001
    color           VARCHAR(20) NOT NULL,            -- RED, GREEN, BLUE, YELLOW, ORANGE, WHITE
    codigo_etiqueta CHAR(10) NOT NULL,               -- ej: ETQ0000001
    estado          BOOLEAN NOT NULL,
    id_palet        CHAR(5)                          -- NULL hasta asignación
)

-- Relación lote ↔ caja (muchos a muchos)
material_caja (
    lote    CHAR(5),
    id_caja CHAR(5),
    PRIMARY KEY (lote, id_caja)
)

-- Relación proveedor ↔ lote
proveedor_material (
    proveedor CHAR(5),
    lote      CHAR(5),
    PRIMARY KEY (proveedor, lote)
)
```

---

## 4. Flujo completo de una tapa

```
SCADA envía gen (color=red, modo Manual)
    │
    ▼
ESP32 recibe → manual_spawn_pending = true, expected_color = red
    │
    ▼
logic-task detecta pending → publica SPAWN (color=red) → RoboDK
    │
    ▼
RoboDK genera tapa en simulación, Delta la mueve bajo cámara
    │
    ▼
Cámara detecta tapa → publica JSON (x, y, color=red, precision=0.98)
    │
    ▼
vision-task filtra (precision > 0.95 ✓) → envía VisionSample al logic-task
    │
    ▼
logic-task valida color (coincide ✓) → mapea red → TOLVA_1
publica PICK (x, y, color, tolva=TOLVA_1, id_cap=C0005) → Delta
pending_tapas["C0005"] = 0 (índice de TOLVA_1)
    │
    ▼
Delta mueve la tapa físicamente a TOLVA_1
SCADA publica done (id_cap=C0005, tolva=TOLVA_1)
    │
    ▼
ESP32 recibe → valida id_cap y tolva, incrementa tolva_counts[0], guarda NVS
```

---

## 5. Flujo completo de una caja

```
tolva_counts[0] >= 2  (TOLVA_1 tiene 2 tapas)
    │
    ▼
logic-task detecta umbral → amr_pending_tolva = 0
ESP32 genera id_caja="C0012", guarda en amr_id_caja
publica goto tolva_1 → AMR
    │
    ▼
AMR llega a tolva_1 → publica ARRIVED (location=tolva_1)
    │
    ▼
ESP32 recibe → amr_arrived_tolva = 0, amr_arrived_at = now()
    │
    ▼ (después de 10 segundos)
logic-task detecta timeout → tolva_counts[0] = 0
publica goto cobot_pick → AMR
publica BOX_COMPLETED (id_caja=C0012, color=red, id_lote=L0042) → db/push
    │
    ├──► mqtt_db_bridge recibe BOX_COMPLETED
    │        inserta caja C0012 en PostgreSQL
    │        inserta material_caja (L0042, C0012) en PostgreSQL
    │
    ▼
AMR llega a cobot_pick → publica ARRIVED (location=cobot_pick)
    │
    ▼
ESP32 recibe → cobot_ready = true
    │
    ▼
logic-task detecta cobot_ready → publica start (id_pallet=P0001, color=red, boxes_stacked=0) → Cobot
cobot_in_progress = true
    │
    ▼
Cobot paletiza la caja → publica completed (id_pallet=P0001)
    │
    ▼
ESP32 recibe → pallet_counts[0]++
    │
    ├── Si pallet_counts[0] >= 12 (PALLET_CAPACITY):
    │       ESP32 publica db/pull (query=operarios) → bridge
    │       Bridge responde en db/pull/response con lista de operarios
    │       ESP32 escoge id_operario aleatoriamente
    │       ESP32 publica caja_paletizada (estado=true, id_operario=OP003) → db/push
    │       ESP32 publica pallet_full (id_palet=P0001) → scada/status
    │       pallet_counts[0] = 0
    │
    └── Si pallet_counts[0] < 12:
            ESP32 publica caja_paletizada (estado=false) → db/push
    │
    ▼
mqtt_db_bridge recibe caja_paletizada
    upsert palet en PostgreSQL
    vincula caja → palet en PostgreSQL
    si estado=true: asigna operario_cierre_id en PostgreSQL
    │
    ▼
cobot_in_progress = false
```

---

## 6. Configuración

### Firmware (`src/config.rs`)

| Constante | Valor por defecto | Descripción |
|---|---|---|
| `WIFI_SSID` | `"PCGato"` | Red Wi-Fi |
| `WIFI_PASS` | `"Coca12345"` | Contraseña Wi-Fi |
| `MQTT_URL` | `"mqtt://broker.hivemq.com:1883"` | Broker MQTT |
| `MQTT_CLIENT_ID` | `"gatomovil"` | ID del cliente MQTT |
| `AMR_TOLVA_THRESHOLD` | `2` | Tapas para despachar AMR |
| `AMR_ARRIVAL_DELAY_SECS` | `10` | Segundos de espera tras llegada del AMR |
| `AMR_WAREHOUSE_LOCATION` | `"cobot_pick"` | Ubicación del Cobot |
| `COBOT_PALLET_ID_BASE` | `10` | ID del primer pallet |
| `COBOT_PALLET_COUNT` | `6` | Número de pallets |
| `PALLET_CAPACITY` | `12` | Cajas por pallet antes de cerrarlo |
| `VALID_COLORS` | `["red","green","yellow","blue","white","orange"]` | Colores aceptados |

### Bridge (`mqtt_db_bridge/.env`)

| Variable | Descripción |
|---|---|
| `MQTT_HOST` | Host del broker MQTT |
| `MQTT_PORT` | Puerto del broker (por defecto 1883) |
| `MQTT_CLIENT_ID` | ID del cliente MQTT del bridge |
| `MQTT_TOPICS` | Lista de topics separados por comas |
| `DATABASE_URL` | Cadena de conexión PostgreSQL |
