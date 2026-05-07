# Trabajo Académico PR2 — GIIROB
## Diseño de una solución de integración en el ámbito de una fábrica

**Grupo:** PR2-A1  
**Asignatura:** Proyectos 2 — Grado en Informática Industrial y Robótica  
**Fecha:** Mayo 2026

---

## 1. Descripción del proyecto

GIIROB es un sistema de producción automatizado que simula una línea de clasificación y paletizado de tapas industriales. El sistema integra un ESP32-S3 como controlador central, RoboDK como entorno de simulación del robot Delta y la cámara de visión, un AMR (robot móvil autónomo) para el transporte de cajas llenas, y un cobot UR3e para el paletizado final.

El ESP32-S3 actúa como cerebro del sistema: recibe órdenes del SCADA, coordina la generación de tapas en la simulación, interpreta las detecciones de la cámara virtual, envía órdenes de clasificación al robot Delta, gestiona el transporte AMR cuando una tolva alcanza su umbral de llenado, y activa el cobot para paletizar las cajas.

Toda la comunicación se realiza mediante el protocolo MQTT sobre el broker público `broker.hivemq.com:1883`, con prefijo de topic `giirob/pr2-A1/`.

---

## 2. Escenario de Integración 1 — Clasificación automática de tapas

### 2.1 Descripción

Este escenario representa el proceso completo de clasificación de una tapa, desde su generación en la simulación hasta su depósito en la tolva correspondiente. Integra cuatro participantes sincronizados vía MQTT.

### 2.2 Participantes

| Participante | Tipo | Rol en la integración |
|---|---|---|
| **SCADA** | Proceso externo (aplicación) | Controlador de lote: inicia el proceso enviando una orden de producción con cantidad y color |
| **ESP32-S3** | Dispositivo embebido (Rust) | Controlador central: gestiona el estado del lote, decide qué tapa generar, qué tolva asignar, y coordina el resto de participantes |
| **RoboDK + Cámara virtual** | Proceso Python (API RoboDK) | Actuador/sensor: recibe la orden de spawn, crea la tapa en la simulación y publica la detección de cámara |
| **Robot Delta (RoboDK)** | Proceso Python (API RoboDK) | Actuador: recibe la orden de pick del ESP32 y ejecuta el movimiento de recogida y depósito en la tolva |

### 2.3 Diagrama de interacciones

```
SCADA ──[gen]──────────────────────────────────────► ESP32-S3
                                                         │
                                               [spawn] ──►──────────── RoboDK
                                                         │              │
                                                         │     [camera/data] ◄──────
                                                         │
                                                [pick] ──►──────────── Delta
                                                         │
                                                    [done] ◄── SCADA (confirmación)
```

### 2.4 Especificación de interacciones

#### Interacción 1.1 — SCADA inicia lote de producción

| Campo | Valor |
|---|---|
| **Emisor** | SCADA |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/scada/action` |
| **Mensaje** | `{"cmd":"gen","lote_id":"L0042","quantity":100}` |
| **Propósito** | Inicia el modo Auto con 100 tapas a clasificar |

En modo Manual el SCADA puede indicar también el color:

```json
{"cmd":"gen","lote_id":"L0042","color":"red","quantity":1}
```

#### Interacción 1.2 — ESP32 ordena generación de tapa en simulación

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | RoboDK (script Python) |
| **Topic** | `giirob/pr2-A1/devices/robodk/action` |
| **Mensaje** | `{"cmd":"spawn","color":"blue","cap_id":"cap_42"}` |
| **Propósito** | Crear la tapa del color indicado en la cinta transportadora de la simulación |

El ESP32 genera el `cap_id` antes de publicar el spawn, de modo que conoce el identificador de la tapa desde el inicio de su ciclo de vida. RoboDK usa ese mismo `cap_id` al publicar la detección de cámara, eliminando cualquier ambigüedad en la trazabilidad. En modo Auto el color rota cíclicamente mediante un contador atómico (ver sección PRA). En modo Manual usa el color especificado por el SCADA.

#### Interacción 1.3 — Cámara virtual publica detección de tapa

| Campo | Valor |
|---|---|
| **Emisor** | RoboDK (script Python — módulo cámara) |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/camera/data` |
| **Mensaje** | `{"x":123.4,"y":56.7,"color":"blue","precision":0.99,"cap_id":"cap_1"}` |
| **Propósito** | Notificar al ESP32 que una tapa ha sido detectada en el campo visual |

El ESP32 ignora detecciones con `precision ≤ 0.95`. El script Python usa `precision: 0.99` fijo ya que la detección es simulada.

#### Interacción 1.4 — ESP32 ordena pick al robot Delta

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | Robot Delta (script Python — módulo Delta) |
| **Topic** | `giirob/pr2-A1/devices/delta/action` |
| **Mensaje** | `{"cmd":"pick","x":123.4,"y":56.7,"color":"blue","tolva":"TOLVA_6","cap_id":"cap_1","reason":"Auto: aceptando tapa color blue (1/100)"}` |
| **Propósito** | Ordenar al Delta que recoja la tapa y la deposite en la tolva indicada |

El ESP32 determina la tolva mediante la tabla de mapeo color→tolva (ver sección 2.5). Antes de emitir el pick, comprueba que `tolva_counts[i] + pending_tolva_counts[i] < umbral` para evitar rebalsamiento.

#### Interacción 1.5 — SCADA confirma depósito de tapa

| Campo | Valor |
|---|---|
| **Emisor** | SCADA |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/scada/status` |
| **Mensaje** | `{"cmd":"done","cap_id":"cap_1","tolva":"TOLVA_6"}` |
| **Propósito** | Confirmar que el Delta depositó la tapa correctamente; el ESP32 actualiza `tolva_counts` |

### 2.5 Mapeo color → tolva

| Color | Tolva |
|---|---|
| `red` | TOLVA_1 |
| `yellow` | TOLVA_2 |
| `green` | TOLVA_3 |
| `white` | TOLVA_4 |
| `orange` | TOLVA_5 |
| `blue` | TOLVA_6 |

Este mapeo está implementado en `src/logic_task.rs` como la función `map_color_to_tolva()`.

### 2.6 Gestión de emergencia dentro del escenario

Si durante la clasificación se recibe una emergencia activa en `giirob/pr2-A1/system/emergency/action`, el ESP32 activa la bandera `emergency_stop: Arc<AtomicBool>` y deja de procesar detecciones de cámara y de generar spawns. Al reanudar (`cmd: "resume"`), el sistema retoma el lote en el punto en que lo dejó.








---

## 3. Escenario de Integración 2 — Paletizado AMR + Cobot

### 3.1 Descripción

Este escenario se activa cuando una tolva alcanza el umbral de llenado. El ESP32 coordina al AMR para recoger la caja llena, trasladarla al área del cobot, y al cobot UR3e para paletizarla. Simultáneamente, la información de la caja se persiste en la base de datos a través del bridge MQTT-DB.

### 3.2 Participantes

| Participante | Tipo | Rol en la integración |
|---|---|---|
| **ESP32-S3** | Dispositivo embebido (Rust) | Controlador central: detecta el umbral de tolva, coordina AMR y cobot, genera la etiqueta de caja |
| **AMR** | Robot móvil autónomo | Actuador de transporte: recibe órdenes `goto`, publica su estado de llegada |
| **Cobot UR3e** | Robot industrial (RoboDK/real) | Actuador de paletizado: recibe la orden `start` y deposita la caja en el pallet indicado |
| **Bridge MQTT-DB** | Proceso Rust | Persistencia: escucha el topic de base de datos y registra cajas y lotes en PostgreSQL |
| **SCADA** | Proceso externo | Monitorización: recibe el estado de AMR y cobot para informar al operario |

### 3.3 Diagrama de interacciones

```
ESP32-S3 ──[goto tolva_N]──────────────────────────► AMR
                                                       │
                                    [arrived tolva_N] ◄─
                                    (espera 10 s)
                                                       │
ESP32-S3 ──[goto cobot_pick + datos caja]─────────► AMR
         ──[box_completed]──────────────────────────► Bridge MQTT-DB ──► PostgreSQL
                                                       │
                                    [arrived cobot_pick] ◄─
                                                       │
ESP32-S3 ──[start pallet]──────────────────────────► Cobot UR3e
                                                       │
                                    [finished pallet] ◄─
```

### 3.4 Especificación de interacciones

#### Interacción 2.1 — ESP32 envía AMR a la tolva llena

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | AMR |
| **Topic** | `giirob/pr2-A1/devices/amr/action` |
| **Mensaje** | `{"cmd":"goto","location":"tolva_3"}` |
| **Propósito** | Ordenar al AMR que vaya a recoger la caja de la tolva que ha alcanzado el umbral |

El ESP32 detecta el umbral en el bucle de `publish_status()`: cuando `tolva_counts[i] >= AMR_TOLVA_THRESHOLD` (configurado en 2 tapas en `config.rs`), registra `amr_pending_tolva` y emite esta orden.

#### Interacción 2.2 — AMR notifica llegada a la tolva

| Campo | Valor |
|---|---|
| **Emisor** | AMR |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/amr/status` |
| **Mensaje** | `{"status":"arrived","location":"TOLVA_1"}` |
| **Propósito** | Notificar que el AMR ha llegado — el ESP32 inicia la espera de 10 segundos |

Al recibir este mensaje, el ESP32 registra `amr_arrived_at = Instant::now()` y espera `AMR_ARRIVAL_DELAY_SECS` (10 s) antes de continuar.

#### Interacción 2.3 — ESP32 envía AMR al área del cobot con datos de la caja

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | AMR |
| **Topic** | `giirob/pr2-A1/devices/amr/action` |
| **Mensaje** | `{"cmd":"goto","location":"cobot_pick"}` |
| **Propósito** | Enviar el AMR al área del cobot; el ESP32 ya tiene `amr_caja_id` en su estado interno desde la llegada a la tolva |

#### Interacción 2.4 — ESP32 persiste caja en la base de datos

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | Bridge MQTT-DB (proceso Rust) |
| **Topic** | `giirob/pr2-A1/db/giirob` |
| **Mensaje** | `{"event":"box_completed","caja_id":"C0012","color":"green","codigo_etiqueta":"ETQ0000003","estado":true,"lotes":["L0042"]}` |
| **Propósito** | Registrar la caja completada en PostgreSQL para trazabilidad de producción |

Este mensaje se emite simultáneamente al envío del AMR al cobot. El bridge lo recibe y ejecuta el `INSERT` en la tabla `caja` y en `material_caja`.

#### Interacción 2.5 — AMR notifica llegada al área del cobot

| Campo | Valor |
|---|---|
| **Emisor** | AMR |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/amr/status` |
| **Mensaje** | `{"status":"arrived","location":"cobot_pick"}` |
| **Propósito** | Activar la secuencia de paletizado del cobot |

#### Interacción 2.6 — ESP32 ordena al cobot paletizar la caja

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | Cobot UR3e |
| **Topic** | `giirob/pr2-A1/devices/cobot/action` |
| **Mensaje** | `{"cmd":"start","id_pallet":10,"mode":"pallet","pos":"pallet1"}` |
| **Propósito** | Iniciar el ciclo de paletizado en la posición del pallet indicado |

El ESP32 gestiona un contador circular de 6 pallets (`cobot_next_pallet`). El `id_pallet` va de 10 a 15 y `pos` de `pallet1` a `pallet6`.

#### Interacción 2.7 — Cobot confirma paletizado completado

| Campo | Valor |
|---|---|
| **Emisor** | Cobot UR3e |
| **Receptor** | ESP32-S3 |
| **Topic** | `giirob/pr2-A1/devices/cobot/status` |
| **Mensaje** | `{"status":"finished","id_pallet":10}` |
| **Propósito** | Notificar que la caja fue depositada correctamente; el ESP32 actualiza `pallet_counts` |

#### Interacción 2.8 — ESP32 persiste paletizado en la base de datos

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | Bridge MQTT-DB |
| **Topic** | `giirob/pr2-A1/db/giirob` |
| **Mensaje** | `{"event":"caja_paletizada","caja_id":"C0012","palet_id":10,"codigo_palet":"PALET000001","color_id":"RED","estado":false}` |
| **Propósito** | El ESP32 publica al topic `db/push`. El bridge vincula la caja al pallet. Cuando `estado:true` (12 cajas), el ESP32 habrá consultado previamente los operarios vía `db/pull` y elegido uno; el `operario_id` viaja en el propio evento y el bridge lo asigna como `operario_cierre_id` |

#### Interacción 2.9 — ESP32 avisa al operario de pallet lleno

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | SCADA |
| **Topic** | `giirob/pr2-A1/devices/scada/status` |
| **Mensaje** | `{"event":"pallet_full","palet_id":10,"codigo_palet":"PALET000001"}` |
| **Propósito** | Notificar al operario que el pallet está lleno (12 cajas) y debe ser retirado; el ESP32 reinicia el contador de ese pallet |

### 3.5 Estados del AMR visibles por el SCADA

El AMR también publica mensajes informativos en `giirob/pr2-A1/devices/amr/status` a los que el SCADA puede suscribirse (el ESP32 los ignora):

| Mensaje | Propósito |
|---|---|
| `{"status":"active","location":"TOLVA_1"}` | AMR en movimiento |
| `{"status":"inactive","location":"TOLVA_1"}` | AMR detenido |

### 3.6 Interacciones de emergencia del AMR

#### Interacción 2.8 — ESP32 notifica emergencia activa al AMR

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | AMR (y resto de dispositivos suscritos) |
| **Topic** | `giirob/pr2-A1/system/emergency/status` |
| **Mensaje** | `{"status":"active","device":"ESP32-S3","sensor":"emergency_button"}` |
| **Propósito** | El AMR se detiene al recibir `status: "active"` |

#### Interacción 2.9 — ESP32 notifica reanudación al AMR

| Campo | Valor |
|---|---|
| **Emisor** | ESP32-S3 |
| **Receptor** | AMR |
| **Topic** | `giirob/pr2-A1/system/emergency/status` |
| **Mensaje** | `{"status":"operative","source":"ESP32-S3","sensor":"resume_button"}` |
| **Propósito** | El AMR reanuda la operación al recibir `status: "operative"` |

#### Interacción 2.10 — AMR publica emergencia propia

| Campo | Valor |
|---|---|
| **Emisor** | AMR |
| **Receptor** | ESP32-S3 (y SCADA) |
| **Topic** | `giirob/pr2-A1/system/emergency/action` |
| **Mensaje** | `{"cmd":"estop","source":"AMR","reason":"collision"}` |
| **Propósito** | El AMR activa la parada de emergencia del sistema cuando detecta un fallo propio (colisión, fallo de rueda, etc.) |

---

## 4. Implementación

### 4.1 Estructura del proyecto

```
c:\p\c\
├── src\
│   ├── main.rs              — inicialización de WiFi, MQTT y lanzamiento de tareas
│   ├── config.rs            — constantes: credenciales, topics, umbrales
│   ├── control_state.rs     — estado compartido del sistema (ControlState)
│   ├── logic_task.rs        — lógica de negocio: spawn, pick, AMR, cobot
│   ├── mqtt_manager.rs      — wrapper del cliente MQTT (EspMqttClient)
│   ├── vision_task.rs       — hilo receptor de detecciones de cámara
│   ├── emergency_task.rs    — hilo de gestión de emergencia
│   └── wifi_manager.rs      — gestión de conexión WiFi
├── mqtt_db_bridge\
│   └── src\main.rs          — bridge MQTT→PostgreSQL (proceso Rust independiente)
├── robodk_giirob.py         — script Python API RoboDK (spawn + pick + cámara virtual)
├── mqtt_messages.md         — referencia completa de todos los mensajes MQTT
└── ROBODK_PYTHON_REQS.md    — especificación detallada del script Python
```

### 4.2 Firmware ESP32-S3 (Rust, esp-idf-svc)

El firmware está implementado en Rust usando el framework `esp-idf-svc`. La decisión de usar Rust en lugar del template Arduino/Processing fue autorizada por los profesores.

**Tareas concurrentes (hilos del sistema):**

| Hilo | Responsabilidad |
|---|---|
| `logic-task` | Bucle principal: genera spawns, procesa detecciones, coordina AMR y cobot |
| `vision-task` | Recibe mensajes MQTT de `camera/data` y los encola hacia `logic-task` |
| `emergency-task` | Escucha `emergency/action`, activa/desactiva el flag `emergency_stop` |
| `mqtt-event-loop` | Bucle interno del cliente MQTT (callback-based) |

La comunicación entre hilos usa canales `std::sync::mpsc` y variables compartidas protegidas con `Arc<Mutex<T>>` y `Arc<AtomicBool>`.

### 4.3 Bridge MQTT-DB (Rust, tokio)

Proceso Rust independiente que actúa como suscriptor MQTT y escritor PostgreSQL. Se suscribe a:

- `giirob/pr2-A1/db/giirob` → inserta/actualiza en tabla `caja` y `material_caja`
- `giirob/pr2-A1/devices/scada/action` → inserta en tabla `material_no_clasificado` y `proveedor_material`

Usa `tokio` para E/S asíncrona, `rumqttc` como cliente MQTT y `tokio-postgres` para la BD.

El parsing de cada topic está separado en funciones puras que devuelven structs tipados (`BoxCompletedEvent`, `GenCommand`), manteniendo el loop principal limpio y permitiendo verificar la lógica de validación con tests unitarios independientes de la red y la base de datos:

```rust
fn parse_box_completed_event(value: &Value) -> Option<BoxCompletedEvent>
fn parse_gen_command(value: &Value)         -> Option<GenCommand>
```

Los tests cubren: normalización del color a mayúsculas, alias `lote`/`lote_id`, valor por defecto de `estado`, rechazo de campos vacíos y rechazo de `quantity ≤ 0`.

### 4.4 Script Python RoboDK

Proceso Python que corre dentro de RoboDK y actúa como puente entre la simulación y el sistema MQTT. Implementa tres módulos lógicos:

1. **Módulo spawn:** recibe `{"cmd":"spawn","color":"..."}`, crea el objeto en la escena y publica la detección de cámara
2. **Módulo pick (Delta):** recibe `{"cmd":"pick",...}`, ejecuta el movimiento del robot Delta y limpia la escena
3. **Módulo emergencia:** activa/desactiva una bandera interna; rechaza picks y spawns mientras está activa

---

## 5. Relación con PRA — Programación Avanzada

### 5.1 Estructuras de datos avanzadas

#### HashMap — tabla de enrutamiento color→tolva y tracking de tapas en vuelo

En `src/control_state.rs`, el estado del sistema incluye:

```rust
pub pending_tapas: HashMap<String, usize>,
```

Este `HashMap` almacena, para cada `cap_id` en vuelo, el índice de tolva asignado. Permite al sistema hacer lookup O(1) cuando llega la confirmación `done` del SCADA, para saber exactamente qué tolva decrementar en `pending_tolva_counts`. Sin esta estructura, habría que recorrer linealmente todas las tapas pendientes para encontrar la coincidencia.

La función `map_color_to_tolva()` implementa una tabla de enrutamiento estática (equivalente a un HashMap con clave `&str` y valor `usize`) para la asignación color→tolva.

#### Arrays de tamaño fijo — contadores de tolvas y pallets

```rust
pub tolva_counts: [u64; 6],
pub pending_tolva_counts: [u64; 6],
pub pallet_counts: [u64; 6],
```

Se usan arrays de tamaño fijo en lugar de `Vec` porque el número de tolvas y pallets es constante y conocido en tiempo de compilación. Esto garantiza acceso O(1) sin heap allocation, crítico en un entorno embebido con memoria limitada.

#### Cola FIFO thread-safe (script Python RoboDK)

En el script Python, la cola de picks del robot Delta usa `queue.Queue` de la librería estándar:

```python
pick_queue = queue.Queue()   # Productor: hilo MQTT
                              # Consumidor: hilo pick_worker
```

Esto implementa el patrón **productor-consumidor**: el hilo MQTT inserta órdenes de pick en la cola sin bloquearse, y el hilo `pick_worker` las consume en orden FIFO, ejecutando un movimiento a la vez. Esta separación garantiza que el cliente MQTT nunca se quede bloqueado esperando a que el robot termine su movimiento.

### 5.2 Algoritmos de programación avanzada

#### Round-robin con contador atómico — selección de color en modo Auto

En `src/logic_task.rs`:

```rust
fn get_random_color() -> &'static str {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let idx = COUNTER.fetch_add(1, Ordering::Relaxed);
    config::VALID_COLORS[idx % config::VALID_COLORS.len()]
}
```

Este algoritmo implementa una **rotación circular (round-robin)** sobre el array de 6 colores válidos usando un contador atómico compartido entre hilos. La operación `fetch_add` con `Ordering::Relaxed` es lock-free: no necesita mutex ni bloqueo, garantizando que cada hilo obtiene su índice sin contención. El módulo asegura que la distribución de colores sea uniforme (cada color aparece exactamente 1 vez cada 6 tapas), lo que equilibra el llenado de las 6 tolvas en modo Auto.

**Justificación frente a alternativas:**
- `rand::random()` daría distribución no uniforme a corto plazo — una tolva podría llenarse mucho antes que otra.
- Un Mutex protegiendo un contador simple funcionaría, pero introduce latencia de bloqueo innecesaria en un entorno embebido.
- El contador atómico con round-robin es O(1), sin heap, sin bloqueo, y con distribución garantizada.

#### Máquina de estados finitos — control del flujo de producción

El sistema implementa una máquina de estados con dos dimensiones ortogonales:

**Dimensión 1 — Modo de operación:**

```
         set_mode:manual          set_mode:auto
 ┌──────────────────────────────────────────────┐
 │                                              │
[Manual] ──────────────────────────────────► [Auto]
   ▲                                              │
   └──────────────────────────────────────────────┘
```

**Dimensión 2 — Estado de emergencia:**

```
   cmd:estop / emergency_button
[Operative] ────────────────────► [Emergency]
    ▲                                   │
    └───────────────────────────────────┘
         cmd:resume / resume_button
```

Ambas dimensiones son independientes: la emergencia puede activarse en cualquier modo, y al resolverse, el sistema retoma el modo que tenía. Esto se implementa con `Arc<AtomicBool>` para la emergencia (accesible desde cualquier hilo sin mutex) y `ControlState.mode: Mode` (enum Rust) para el modo de operación.

---

## 6. Relación con GDI — Gestión de Datos para la Industria

### 6.1 Motivación de la integración con base de datos

El sistema necesita trazabilidad completa del proceso de producción: qué cajas se fabricaron, con qué lotes de material, cuándo, y en qué pallets quedaron almacenadas. Esta información debe persistir más allá de la sesión de producción para poder generar informes, auditorías y consultas por parte del SCADA o de sistemas ERP externos.

### 6.2 Esquema de la base de datos

```sql
-- Proveedor de material
CREATE TABLE IF NOT EXISTS proveedor (
    num_proveedor     CHAR(5)      PRIMARY KEY,
    cif_nif           VARCHAR(20)  NOT NULL UNIQUE,
    nombre            VARCHAR(100) NOT NULL,
    certificacion_iso BOOLEAN      NOT NULL
);

-- Tablas multivaluadas del proveedor
CREATE TABLE IF NOT EXISTS proveedor_direccion (
    proveedor CHAR(5),
    direccion VARCHAR(200),
    PRIMARY KEY (proveedor, direccion),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_tlf (
    proveedor    CHAR(5),
    tlf_contacto VARCHAR(20),
    PRIMARY KEY (proveedor, tlf_contacto),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_correo (
    proveedor          CHAR(5),
    correo_electronico VARCHAR(100),
    PRIMARY KEY (proveedor, correo_electronico),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_categoria (
    proveedor CHAR(5),
    categoria VARCHAR(50),
    PRIMARY KEY (proveedor, categoria),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

-- Lote de material no clasificado recibido de proveedor
CREATE TABLE IF NOT EXISTS material_no_clasificado (
    lote_id                  CHAR(5)      PRIMARY KEY,
    fecha_inicio             DATE         NOT NULL,
    fecha_fin                DATE,
    total_tapas_entrada      INT          NOT NULL,
    total_tapas_clasificadas INT          DEFAULT 0,
    observaciones            VARCHAR(200),
    CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio),
    CHECK (total_tapas_entrada      >= 0),
    CHECK (total_tapas_clasificadas >= 0),
    CHECK (total_tapas_clasificadas <= total_tapas_entrada)
);

-- Relación proveedor ↔ lote
CREATE TABLE IF NOT EXISTS proveedor_material (
    proveedor CHAR(5),
    lote_id   CHAR(5),
    PRIMARY KEY (proveedor, lote_id),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor),
    FOREIGN KEY (lote_id)   REFERENCES material_no_clasificado(lote_id)
);

-- Operario de cierre de palet
CREATE TABLE IF NOT EXISTS operario (
    operario_id INTEGER      PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,
    apellido    VARCHAR(100) NOT NULL
);

-- Palet de almacenamiento final
CREATE TABLE IF NOT EXISTS palet (
    palet_id           INTEGER  PRIMARY KEY,
    codigo_palet       CHAR(10) NOT NULL UNIQUE,
    color_id           CHAR(5)  NOT NULL,
    estado             BOOLEAN  NOT NULL,
    operario_cierre_id INTEGER,
    FOREIGN KEY (operario_cierre_id) REFERENCES operario(operario_id)
);

-- Caja completada (llena de tapas clasificadas de un color)
CREATE TABLE IF NOT EXISTS caja (
    caja_id         CHAR(5)     PRIMARY KEY,
    color           VARCHAR(20) NOT NULL,
    codigo_etiqueta CHAR(10)    NOT NULL,
    estado          BOOLEAN     NOT NULL,
    palet_id        INTEGER,
    FOREIGN KEY (palet_id) REFERENCES palet(palet_id),
    CHECK (color IN ('RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'WHITE'))
);

-- Relación material ↔ caja (qué lotes contribuyeron a una caja)
CREATE TABLE IF NOT EXISTS material_caja (
    lote_id CHAR(5),
    caja_id CHAR(5),
    PRIMARY KEY (lote_id, caja_id),
    FOREIGN KEY (lote_id) REFERENCES material_no_clasificado(lote_id),
    FOREIGN KEY (caja_id) REFERENCES caja(caja_id)
);
```

### 6.3 Componente de integración — Bridge MQTT-DB

El bridge (`mqtt_db_bridge/`) es un proceso Rust independiente que escucha dos topics MQTT y persiste los datos en PostgreSQL:

**Flujo 1 — Registro de lote:**

```
SCADA ──[gen, lote_id, quantity, proveedor]──► Bridge ──► INSERT material_no_clasificado
                                                       ──► INSERT proveedor_material
```

**Flujo 2 — Registro de caja completada:**

```
ESP32-S3 ──[box_completed, caja_id, color, etiqueta, lotes]──► Bridge ──► INSERT/UPDATE caja
                                                                        ──► INSERT material_caja
```

El bridge usa `ON CONFLICT DO UPDATE` en la tabla `caja` para ser idempotente: si el mismo mensaje llega dos veces (MQTT QoS 1 garantiza "at least once"), no duplica registros.

#### Creación de una caja

**ESP32-S3** (`src/logic_task.rs`) — publicación al broker cuando el detector de color cierra una caja:

```rust
let db_msg = json!({
    "event": "box_completed",
    "caja_id": caja_id,           // p.ej. "C0001"
    "color": color,               // p.ej. "red"
    "codigo_etiqueta": etiqueta,  // p.ej. "ETQ0000001"
    "estado": estado,             // true = correcta, false = defectuosa
    "lotes": lotes                // vec de lote_id que componen la caja
})
.to_string();
mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &db_msg);
// topic: giirob/pr2-A1/db/push
```

**Bridge** (`mqtt_db_bridge/src/bridge.rs`) — recepción y persistencia en PostgreSQL:

```rust
if event.eq_ignore_ascii_case("box_completed") {
    if let Some(event) = parse_box_completed_event(&value) {
        // 1. Insertar o actualizar la caja (idempotente con ON CONFLICT)
        pg.execute(
            &insert_caja_stmt,
            &[&event.caja_id, &event.color_db, &event.etiqueta, &event.estado],
        ).await?;

        // 2. Vincular cada lote de material a la caja
        for lote_id in event.lotes {
            pg.execute(
                &insert_material_caja_stmt,
                &[&lote_id, &event.caja_id],
            ).await?;
        }
    }
}
```

El `INSERT` sobre `caja` usa `ON CONFLICT (caja_id) DO UPDATE SET color = EXCLUDED.color, ...` **sin tocar `palet_id`**, de modo que una re-entrega del mismo evento no borra la vinculación al palet si ya se había paletizado.

---

**Flujo 3 — Registro de caja paletizada:**

```
ESP32-S3 ──[caja_paletizada, caja_id, palet_id, estado]──► Bridge ──► UPSERT palet
                                                                    ──► UPDATE caja.palet_id
                                                                    ──► UPDATE palet.operario_cierre_id  (si estado=true)
```

#### Creación de un palet

**ESP32-S3** (`src/mqtt_manager.rs`) — publicación tras recibir `FINISHED` del cobot (*pendiente de implementación*):

```rust
// Al recibir status=FINISHED desde el cobot:
state.pallet_counts[index] += 1;
state.cobot_in_progress = false;

// TODO: publicar caja_paletizada a db/push
// Estructura del mensaje:
// {
//   "event": "caja_paletizada",
//   "caja_id":      "<id de la caja recién paletizada>",
//   "palet_id":     <COBOT_PALLET_ID_BASE + index>,
//   "codigo_palet": "PALET<07d>",
//   "color_id":     <id de color en BD>,
//   "estado":       <true si pallet_counts[index] >= PALLET_CAPACITY>,
//   "operario_id":  <obtenido vía db/pull query="operarios">   // solo si estado=true
// }
// mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &db_msg);
```

**Bridge** (`mqtt_db_bridge/src/bridge.rs`) — recepción y persistencia en PostgreSQL:

```rust
} else if event.eq_ignore_ascii_case("caja_paletizada") {
    if let Some(ev) = parse_caja_paletizada(&value) {
        // 1. Crear o actualizar el palet
        pg.execute(
            &upsert_palet_stmt,
            &[&ev.palet_id, &ev.codigo_palet, &ev.color_id, &ev.estado],
        ).await?;

        // 2. Vincular la caja al palet (UPDATE caja SET palet_id = ...)
        pg.execute(
            &link_caja_palet_stmt,
            &[&ev.palet_id, &ev.caja_id],
        ).await?;

        // 3. Si el palet se cierra, asignar el operario de cierre
        if ev.estado {
            if let Some(operario_id) = ev.operario_id {
                pg.execute(
                    &set_operario_cierre_stmt,
                    &[&operario_id, &ev.palet_id],
                ).await?;
            }
        }
    }
}
```

### 6.4 Generación de etiquetas

El ESP32 genera los códigos de etiqueta automáticamente con el formato `ETQ0000001` usando un contador atómico en `next_etiqueta()` (incrementado de forma segura entre hilos). El bridge almacena el color en mayúsculas (`color.to_ascii_uppercase()`).

---

## 7. Repositorio Git

El proyecto está desarrollado íntegramente en un repositorio Git. La rama principal es `main` y el desarrollo activo se realiza en la rama `prototipado`. El historial de commits refleja la evolución del proyecto: firmware ESP32, bridge MQTT-DB, documentación de integración y especificación del script RoboDK.

El repositorio contiene:
- `src/` — firmware ESP32-S3 en Rust
- `mqtt_db_bridge/` — bridge MQTT→PostgreSQL en Rust
- `mqtt_messages.md` — referencia completa de mensajes MQTT
- `ROBODK_PYTHON_REQS.md` — especificación del script Python RoboDK
- `run_all.ps1` — script para desplegar el sistema completo

---

## 8. Guía de despliegue

### Requisitos previos
- Rust toolchain con target `riscv32imc-esp-espidf` (ESP32-S3)
- `cargo` con `espup` configurado
- Python 3.x con `paho-mqtt` y `robolink` instalados
- PostgreSQL accesible con la URL configurada en `mqtt_db_bridge/.env`

### Pasos para ejecutar

1. **Flashear el firmware en el ESP32:**
   ```powershell
   cd c:\p\c
   cargo run
   ```

2. **Lanzar el bridge MQTT-DB:**
   ```powershell
   cd c:\p\c\mqtt_db_bridge
   cargo run
   ```
   *(o usar `run_all.ps1` para lanzar ambos juntos)*

3. **Lanzar el script RoboDK:**
   - Abrir RoboDK con la escena del sistema GIIROB
   - Ejecutar `robodk_giirob.py` desde el editor Python de RoboDK

4. **Conectar el SCADA** al broker `broker.hivemq.com:1883` y publicar en `giirob/pr2-A1/devices/scada/action` para iniciar un lote.
