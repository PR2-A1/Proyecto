# Implementación — Demo de Escenarios de Integración

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Base de datos](#2-base-de-datos)
3. [Bridge MQTT-PostgreSQL](#3-bridge-mqtt-postgresql)
4. [Firmware ESP32 — Escenario 1 (AMR → Cobot)](#4-firmware-esp32--escenario-1-amr--cobot)
5. [Firmware ESP32 — Escenario 2 (Lote → RoboDK)](#5-firmware-esp32--escenario-2-lote--robodk)
6. [Python RoboDK](#6-python-robodk)
7. [Patrones de diseño relevantes](#7-patrones-de-diseño-relevantes)

---

## 1. Arquitectura general

```
┌─────────────────────────────────────────────────────────────────────┐
│                       broker.hivemq.com:1883                        │
└─────┬──────────────────┬──────────────────┬───────────────┬─────────┘
      │                  │                  │               │
  amr/status       db/push            db/pull          camera/data
  cobot/status     (ESP32→Bridge)     (ESP32→Bridge)   (RoboDK→ESP32)
  cobot/action                        db/pull/response
  robodk/action                       (Bridge→ESP32)
      │
┌─────┴──────────┐    ┌─────────────┐    ┌──────────────┐    ┌───────────┐
│   ESP32-S3     │    │    Bridge   │    │   RoboDK     │    │    AMR    │
│  (firmware     │    │  (Rust PC)  │    │  (Python)    │    │  (físico) │
│   Rust)        │    │             │    │              │    │           │
│                │    │ PostgreSQL  │    │  Escena 3D   │    │           │
│  escenario1.rs │    │   schema    │    │  + cámara    │    │           │
│  escenario2.rs │    │   .sql      │    │  virtual     │    │           │
└────────────────┘    └─────────────┘    └──────────────┘    └───────────┘
```

El ESP32-S3 es el **único controlador** del sistema. El bridge solo persiste datos; RoboDK solo simula la escena física. Ninguno toma decisiones de negocio.

---

## 2. Base de datos

### 2.1 Esquema relevante

```sql
-- Lotes de material sin clasificar (fuente del Escenario 2)
CREATE TABLE material_no_clasificado (
    lote_id                  CHAR(5)  PRIMARY KEY,
    total_tapas_entrada      INTEGER  NOT NULL,
    total_tapas_clasificadas INTEGER  NOT NULL DEFAULT 0,
    color                    VARCHAR(16) NOT NULL DEFAULT 'red'
);

-- Palets de cajas clasificadas (destino del Escenario 1)
CREATE TABLE palet (
    palet_id           INTEGER PRIMARY KEY,
    codigo_palet       VARCHAR(16) NOT NULL,
    color_id           VARCHAR(16) NOT NULL,
    estado             BOOLEAN NOT NULL DEFAULT FALSE,
    operario_cierre_id INTEGER REFERENCES operario(operario_id)
);

-- Operarios disponibles en el sistema
CREATE TABLE operario (
    operario_id SERIAL PRIMARY KEY,
    nombre      VARCHAR(64) NOT NULL,
    apellido    VARCHAR(64) NOT NULL,
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);
```

### 2.2 Sentencia SQL destacada — UPSERT de palet

```sql
INSERT INTO palet (palet_id, codigo_palet, color_id, estado)
VALUES ($1, $2, $3, $4)
ON CONFLICT (palet_id) DO UPDATE
    SET estado = EXCLUDED.estado;
```

`ON CONFLICT DO UPDATE` hace la operación **idempotente**: si el ESP32 reenvía el mismo evento dos veces (MQTT QoS 1 garantiza *at-least-once*), no se duplica el registro. Solo se actualiza `estado`; las demás columnas se dejan intactas para no sobreescribir datos ya consolidados.

### 2.3 Consulta lote pendiente (Escenario 2)

```sql
SELECT lote_id,
       total_tapas_entrada - total_tapas_clasificadas AS pendientes,
       color
FROM   material_no_clasificado
WHERE  total_tapas_clasificadas < total_tapas_entrada
ORDER  BY fecha_inicio ASC
LIMIT  1;
```

Devuelve el lote más antiguo con tapas pendientes de clasificar — el ESP32 lo utiliza para generar la siguiente tapa en RoboDK.

---

## 3. Bridge MQTT-PostgreSQL

El bridge es un proceso Rust asíncrono (`tokio`) que escucha dos topics y responde o persiste según el tipo de mensaje.

### 3.1 Estructura del bucle principal

```rust
loop {
    match eventloop.poll().await {
        Ok(Event::Incoming(Packet::Publish(pub_msg))) => {
            match pub_msg.topic.as_str() {
                TOPIC_DB_PUSH => handle_db_push(...).await,
                TOPIC_DB_PULL => handle_db_pull(...).await,
                _ => {}
            }
        }
        Err(e) => { error!(...); tokio::time::sleep(...).await; }
        _ => {}
    }
}
```

El uso de `match` exhaustivo sobre el topic garantiza que mensajes no esperados se descartan de forma explícita, sin panics.

### 3.2 Preparación anticipada de sentencias SQL

```rust
let upsert_palet = pg.prepare(
    "INSERT INTO palet ... ON CONFLICT ... DO UPDATE ...",
).await?;
```

Las sentencias se preparan **una sola vez** al arrancar, antes del bucle. `tokio-postgres` envía el plan al servidor PostgreSQL en el handshake; en cada ejecución solo viajan los parámetros. Esto reduce latencia y evita recompilaciones en el servidor.

### 3.3 Handler `db/push` — caja_paletizada

```rust
async fn handle_db_push(pg, payload, upsert_palet, link_caja_palet, set_op_cierre) {
    // 1. UPSERT del palet
    pg.execute(upsert_palet, &[&ev.palet_id, &ev.codigo_palet, &ev.color_id, &ev.estado]).await?;

    // 2. Vincular caja al palet
    pg.execute(link_caja_palet, &[&ev.palet_id, &ev.caja_id]).await?;

    // 3. Asignar operario de cierre solo si el pallet se cierra (estado=true)
    if ev.estado {
        if let Some(op_id) = ev.operario_id {
            pg.execute(set_op_cierre, &[&op_id, &ev.palet_id]).await?;
        }
    }
}
```

### 3.4 Handler `db/pull` — consultas del ESP32

```rust
async fn handle_db_pull(pg, mqtt, payload, q_operarios, q_lote_pendiente) {
    match query {
        "operarios" => {
            let rows = pg.query(q_operarios, &[]).await?;
            let lista = rows.iter().map(|r| json!({
                "operario_id": r.get::<_, i32>(0),
                "nombre":      r.get::<_, &str>(1),
                "apellido":    r.get::<_, &str>(2),
            })).collect::<Vec<_>>();
            mqtt.publish(TOPIC_PULL_RESP, json!({ "operarios": lista })).await;
        }
        "lote_pendiente" => {
            if let Some(row) = pg.query_opt(q_lote_pendiente, &[]).await? {
                mqtt.publish(TOPIC_PULL_RESP, json!({
                    "lote_id":  row.get::<_, &str>(0),
                    "quantity": row.get::<_, i64>(1),
                    "color":    row.get::<_, &str>(2),
                })).await;
            }
        }
    }
}
```

---

## 4. Firmware ESP32 — Escenario 1 (AMR → Cobot)

### 4.1 Inicialización y canales

```rust
// main.rs
let (cobot_evt_tx, cobot_evt_rx) = sync_channel::<u32>(4);
let pull_slot = Arc::new(Mutex::new(None::<SyncSender<String>>));

let mqtt = Arc::new(Mutex::new(
    MqttManager::connect_and_subscribe(
        Arc::clone(&demo_state),
        cobot_evt_tx,      // capturado por el callback MQTT
        camera_tx,
        Arc::clone(&pull_slot),
    )?,
));

thread::spawn(move || escenario1::run(mqtt, state, cobot_evt_rx, pull_slot));
```

### 4.2 Flujo completo (escenario1.rs)

```
AMR publica ARRIVED
  → callback MQTT: state.cobot_ready = true
  → escenario1::wait_for_cobot_ready() desbloquea
  → publica {"cmd":"start"} a cobot/action
  → espera en cobot_evt_rx.recv_timeout(60s)
  → callback MQTT: cobot FINISHED → cobot_evt_tx.try_send(pallet_id)
  → query_operarios() vía db/pull (patron petición-respuesta)
  → publish_caja_paletizada() a db/push
```

### 4.3 Patrón petición-respuesta sobre db/pull

Esta es la estructura más avanzada del firmware. Como MQTT es asíncrono y el ESP32 usa hilos (no `async/await`), se necesita un mecanismo para "esperar" la respuesta del bridge sin bloquear el callback:

```rust
fn query_operarios(mqtt: &Arc<Mutex<MqttManager>>, pull_slot: &PullSlot) -> Option<i32> {
    // 1. Crear canal de un solo uso
    let (tx, rx) = sync_channel::<String>(1);

    // 2. Registrar el sender en el slot compartido
    //    El callback MQTT lo usará cuando llegue db/pull/response
    { *pull_slot.lock().unwrap() = Some(tx); }

    // 3. Publicar la consulta
    mqtt.lock().unwrap().publish_text(TOPIC_DB_PULL, r#"{"query":"operarios"}"#);

    // 4. Bloquear el hilo de escenario (no el de MQTT) hasta recibir respuesta
    let result = rx.recv_timeout(Duration::from_secs(5)).ok()
        .and_then(|s| parse_and_pick_operario(&s));

    // 5. Liberar el slot
    { *pull_slot.lock().unwrap() = None; }

    result
}
```

**Callback MQTT** (hilo separado):
```rust
TOPIC_DB_PULL_RESP => {
    if let Ok(slot) = pull_slot.try_lock() {
        if let Some(tx) = slot.as_ref() {
            let _ = tx.try_send(mensaje.to_string());
        }
    }
}
```

El canal `sync_channel(1)` garantiza que no se pierden mensajes: si el bridge responde antes de que el hilo de escenario llegue a `recv_timeout`, el mensaje queda en el buffer del canal.

### 4.4 Selección de operario

```rust
// Selección pseudoaleatoria: usa los nanosegundos del reloj del sistema
let idx = (SystemTime::now()
    .duration_since(UNIX_EPOCH)
    .unwrap_or_default()
    .subsec_nanos() as usize)
    % lista.len();
let operario_id = lista[idx]["operario_id"].as_i64().map(|v| v as i32);
```

Se usan nanosegundos del reloj en lugar de un generador de números aleatorios porque `rand` no está disponible en `no_std` ESP-IDF sin configuración adicional.

---

## 5. Firmware ESP32 — Escenario 2 (Lote → RoboDK)

### 5.1 Flujo completo (escenario2.rs)

```
escenario2::run() entra en bucle:
  → fetch_lote() vía db/pull (patron petición-respuesta)
  → si None: esperar 10 s y reintentar
  → construir cap_id incremental ("C0001", "C0002", ...)
  → publicar {"cmd":"spawn","color","cap_id"} a robodk/action
  → esperar en camera_rx.recv_timeout(15s)
  → callback MQTT: camera/data → camera_tx.try_send(json)
  → loguear posición confirmada
```

### 5.2 Fetch de lote pendiente

```rust
fn fetch_lote(mqtt, pull_slot) -> Option<LoteInfo> {
    let (tx, rx) = sync_channel::<String>(1);
    { *pull_slot.lock().unwrap() = Some(tx); }

    mqtt.lock().unwrap().publish_text(
        TOPIC_DB_PULL,
        r#"{"query":"lote_pendiente"}"#,
    );

    let result = rx.recv_timeout(Duration::from_secs(5))
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|val| {
            // Si lote_id es null, el bridge indica que no hay lotes
            val.get("lote_id")?.as_str()?;
            Some(LoteInfo {
                lote_id:  val["lote_id"].as_str()?.to_string(),
                quantity: val["quantity"].as_i64()? as i32,
                color:    val["color"].as_str().unwrap_or("red").to_string(),
            })
        });

    { *pull_slot.lock().unwrap() = None; }
    result
}
```

---

## 6. Python RoboDK

### 6.1 Spawn de tapa en la escena

```python
def _spawn_tapa(payload, mqttc):
    color  = payload["color"].lower()
    cap_id = payload["cap_id"]

    # Clonar la plantilla (Copy/Paste no es thread-safe en RoboDK)
    with _rdk_lock:
        RDK.Copy(template)
        cap = RDK.Paste()

    cap.setName(cap_id)
    cap.Recolor(config.COLOR_RGB[color])

    frame = RDK.Item(config.SPAWN_FRAME, robolink.ITEM_TYPE_FRAME)
    cap.setPoseAbs(frame.PoseAbs() if frame.Valid() else template.PoseAbs())

    time.sleep(config.SPAWN_DELAY_S)

    # Leer posicion absoluta y publicar como deteccion de camara
    pose = cap.PoseAbs()
    mqttc.publish(config.TOPIC_CAMERA_DATA, json.dumps({
        "x":         round(pose[0, 3], 2),
        "y":         round(pose[1, 3], 2),
        "color":     color,
        "precision": config.PICK_PRECISION,
        "cap_id":    cap_id,
    }), qos=config.MQTT_QOS)
```

### 6.2 Threading y seguridad

- `_rdk_lock = threading.Lock()`: protege `RDK.Copy()` / `RDK.Paste()` que no son thread-safe.
- El handler MQTT es no bloqueante: lanza un `Thread(daemon=True)` para cada spawn, permitiendo recibir nuevos mensajes mientras la animación se ejecuta.
- `paho-mqtt` API legacy (sin `CallbackAPIVersion`): compatible con la versión embebida en RoboDK.

---

## 7. Patrones de diseño relevantes

### 7.1 Productor-consumidor con `sync_channel`

Todos los canales entre el callback MQTT y los hilos de escenario usan `std::sync::mpsc::sync_channel(N)`:

| Canal           | Productor       | Consumidor      | Capacidad |
|-----------------|-----------------|-----------------|-----------|
| `cobot_evt_tx`  | callback MQTT   | escenario1      | 4         |
| `camera_tx`     | callback MQTT   | escenario2      | 16        |
| `pull_slot`     | escenario activo| callback MQTT   | 1 (slot)  |

`sync_channel` es acotado: si el buffer está lleno, el productor bloquea. Esto crea **back-pressure** natural — el sistema no genera tapas más rápido de lo que el cobot puede procesar.

### 7.2 Slot de petición-respuesta (`PullSlot`)

```rust
type PullSlot = Arc<Mutex<Option<SyncSender<String>>>>;
```

Un `Option<SyncSender>` dentro de un `Mutex` actúa como **rendezvous point** entre el hilo que hace una consulta y el callback que recibe la respuesta. El `Option` garantiza que solo un escenario puede tener una consulta en vuelo en un momento dado.

### 7.3 Concurrencia sin `async` en ESP32

El ESP32 con `esp-idf-svc` ejecuta Rust sobre FreeRTOS. No hay `tokio` ni `async/await`; la concurrencia se implementa con hilos de sistema operativo y `std::sync`. El patrón `recv_timeout` en lugar de `await` permite bloquear un hilo específico sin afectar al callback MQTT, que corre en su propio hilo gestionado por `EspMqttClient`.
