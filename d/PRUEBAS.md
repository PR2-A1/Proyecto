# Pruebas Manuales — Demo Escenarios de Integración

## Herramientas necesarias

| Herramienta | Uso |
|-------------|-----|
| MQTT Explorer / mqttx | Publicar mensajes y observar topics |
| psql / DBeaver | Consultar y modificar la base de datos |
| Monitor serie (espflash / VSCode) | Ver logs del ESP32 en tiempo real |
| RoboDK con escena cargada | Visualizar el spawn de tapas (Escenario 2) |

**Broker público:** `broker.hivemq.com:1883`  
**Prefijo de todos los topics:** `giirob/pr2-A1/`

---

## Arquitectura del firmware

El ESP32 ejecuta una sola tarea lógica (`logic_task`). En cada iteración:

1. Si el AMR marcó `cobot_ready = true` → **Escenario 1** (AMR → Cobot → DB)
2. Si no → **Escenario 2** (consulta lote → RoboDK → Cámara)

Los logs llevan prefijo `[ESC1]` o `[ESC2]`. Al arrancar, el ESP32 entra directamente en ciclos de ESC2 mientras no llegue un ARRIVED del AMR.

---

## Preparación previa

### 1. Cargar la base de datos

```powershell
# Windows
$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
$env:PGPASSWORD = "postgres"
& $psql -h 127.0.0.1 -U postgres -d giirob -f db\schema.sql
```

```bash
# macOS/Linux
psql "host=127.0.0.1 user=postgres password=postgres dbname=giirob" -f db/schema.sql
```

> Si la BD ya tiene datos, el schema usa `ON CONFLICT DO NOTHING` y no sobreescribe.
> Para resetear completamente, ejecutar primero:
> ```sql
> TRUNCATE palet CASCADE;
> UPDATE material_no_clasificado SET total_tapas_clasificadas = 0;
> UPDATE caja SET palet_id = NULL;
> ```

### 2. Verificar estado inicial

```sql
-- Resultado esperado: 3 filas
SELECT operario_id, nombre, apellido FROM operario;
```
```
 operario_id | nombre | apellido
-------------+--------+----------
           1 | Carlos | Martinez
           2 | Laura  | Gomez
           3 | Miguel | Lopez
```

```sql
-- Resultado esperado: 3 tapas pendientes en cada lote
SELECT lote_id, total_tapas_entrada, total_tapas_clasificadas
FROM   material_no_clasificado;
```
```
 lote_id | total_tapas_entrada | total_tapas_clasificadas
---------+---------------------+-------------------------
 L0001   |                   3 |                        0
 L0002   |                   3 |                        0
```

```sql
-- Resultado esperado: 3 cajas sin palet asignado
SELECT caja_id, color, palet_id FROM caja;
```
```
 caja_id | color | palet_id
---------+-------+----------
 C0001   | RED   |
 C0002   | RED   |
 C0003   | BLUE  |
```

```sql
-- Debe estar vacía al inicio
SELECT * FROM palet;
```
```
(0 filas)
```

### 3. Arrancar el bridge

```powershell
cd C:\p\d\bridge
cargo run
```

**Salida esperada:**
```
INFO bridge_demo: Conectando a MQTT broker.hivemq.com:1883
INFO bridge_demo: Suscrito a giirob/pr2-A1/db/push y giirob/pr2-A1/db/pull
INFO bridge_demo: Conectando a PostgreSQL...
INFO bridge_demo: PostgreSQL conectado
INFO bridge_demo: Bridge listo — esperando mensajes MQTT...
```

### 4. Flashear y monitorear el ESP32

```powershell
cd C:\p\d\esp32
cargo run
```

**Salida esperada al arrancar:**
```
I (...) demo_integracion::wifi_manager: Esperando Wi-Fi...
I (...) demo_integracion::mqtt_manager: MQTT conectado
I (...) demo_integracion::mqtt_manager: Suscrito id=1
I (...) demo_integracion::logic_task: [LOGIC] Tarea unificada iniciada
```

Inmediatamente el ESP32 empieza ciclos de ESC2:
```
I (...) demo_integracion::mqtt_manager: Publicado en [giirob/pr2-A1/db/pull]: {"query":"lote_pendiente"}
I (...) demo_integracion::mqtt_manager: db/pull/response: {"color":"red","lote_id":"L0001","quantity":3}
I (...) demo_integracion::logic_task: [ESC2] Lote obtenido: id=L0001 color=red cantidad=3
I (...) demo_integracion::mqtt_manager: Publicado en [giirob/pr2-A1/devices/robodk/action]: {...}
I (...) demo_integracion::logic_task: [ESC2] Spawn enviado a RoboDK — cap_id=C0001
```

### 5. Abrir RoboDK (solo Escenario 2)

Abrir RoboDK con la escena y ejecutar `robodk/MqttListener.py` desde el editor Python interno.

---

## Bloque A — Escenario 1: AMR → Cobot → Operario → DB

### A.1 — AMR llega a cobot_pick

**Publicar** en `giirob/pr2-A1/devices/amr/status`:

```json
{
  "status":   "ARRIVED",
  "location": "cobot_pick"
}
```

**Log ESP32:**
```
I (...) demo_integracion::mqtt_manager: AMR llegó a cobot_pick — cobot_ready=true
I (...) demo_integracion::logic_task: [ESC1] Ordenando paletizar — caja=C000X color=RED pallet=10
```

> `caja=C000X` es el último `cap_id` generado por ESC2 antes de que llegara el ARRIVED.

**Topic `giirob/pr2-A1/devices/cobot/action` recibe:**

```json
{
  "cmd":       "start",
  "id_pallet": 10,
  "caja_id":   "C0001",
  "color":     "RED",
  "mode":      "pallet",
  "location":  "PALLET_1",
  "device":    "ESP32-S3"
}
```

**Log bridge:**
```
(ninguno — el cobot/action no pasa por el bridge)
```

---

### A.2 — Cobot termina de paletizar

**Publicar** en `giirob/pr2-A1/devices/cobot/status`:

```json
{
  "status":    "COMPLETED",
  "id_pallet": 10
}
```

**Log ESP32:**
```
I (...) demo_integracion::mqtt_manager: Cobot COMPLETED pallet_id=10
I (...) demo_integracion::logic_task: [ESC1] Cobot confirmó COMPLETED pallet_id=10
```

> La consulta de operarios **solo ocurre en el ciclo 12** (pallet lleno). En ciclos 1–11 no se consulta.

**Log bridge:**
```
(ninguno — operarios solo se consultan al cerrar el pallet)
```

---

### A.3 — caja_paletizada publicada (pallet no lleno, ciclo 1)

El pallet aún no está cerrado (`estado=false`) — no se consulta operario ni se incluye `operario_id`.

**Topic `giirob/pr2-A1/db/push` recibe:**

```json
{
  "event":        "caja_paletizada",
  "caja_id":      "C0001",
  "palet_id":     10,
  "codigo_palet": "PAL0000010",
  "color_id":     "RED",
  "estado":       false
}
```

**Log bridge:**
```
INFO bridge_demo: Mensaje en [giirob/pr2-A1/db/push]: {"event":"caja_paletizada",...}
INFO bridge_demo: Paletizando: caja=C0001 palet=10 estado=false
INFO bridge_demo: Palet 10 upserted
INFO bridge_demo: Caja C0001 vinculada a palet 10 (1 filas)
```

**Verificar en BD:**

```sql
SELECT palet_id, codigo_palet, estado, operario_cierre_id
FROM   palet WHERE palet_id = 10;
```
```
 palet_id | codigo_palet | estado | operario_cierre_id
----------+--------------+--------+--------------------
       10 | PAL0000010   | f      |
```

```sql
SELECT caja_id, palet_id FROM caja WHERE caja_id = 'C0001';
```
```
 caja_id | palet_id
---------+----------
 C0001   |       10
```

---

### A.4 — Pallet lleno (ciclo 2) — asignación de operario de cierre

Repetir A.1 + A.2 una segunda vez (`PALLET_CAPACITY = 2`).

**Topic `giirob/pr2-A1/db/push` en el ciclo 2:**

```json
{
  "event":        "caja_paletizada",
  "caja_id":      "C0002",
  "palet_id":     10,
  "codigo_palet": "PAL0000010",
  "color_id":     "RED",
  "estado":       true,
  "operario_id":  2
}
```

**Log ESP32** (solo en el ciclo 2, al cerrar el pallet):
```
I (...) demo_integracion::mqtt_manager: Publicado en [giirob/pr2-A1/db/pull]: {"query":"operarios"}
I (...) demo_integracion::logic_task: [ESC1] Elegido operario_id=Some(2) (Laura)
I (...) demo_integracion::logic_task: [ESC1] Operario seleccionado: Some(2)
```

**Log bridge:**
```
INFO bridge_demo: Mensaje en [giirob/pr2-A1/db/pull]: {"query":"operarios"}
INFO bridge_demo: Operarios enviados: 3 registros
INFO bridge_demo: Paletizando: caja=C0002 palet=10 estado=true
INFO bridge_demo: Palet 10 upserted
INFO bridge_demo: Caja C0002 vinculada a palet 10 (1 filas)
INFO bridge_demo: Operario 2 asignado como cierre del palet 10
```

**Verificar en BD:**

```sql
SELECT palet_id, estado, operario_cierre_id
FROM   palet WHERE palet_id = 10;
```
```
 palet_id | estado | operario_cierre_id
----------+--------+--------------------
       10 | t      |                  2
```

```sql
SELECT o.nombre, o.apellido
FROM   operario o
JOIN   palet p ON p.operario_cierre_id = o.operario_id
WHERE  p.palet_id = 10;
```
```
 nombre | apellido
--------+----------
 Laura  | Gomez
```

---

### A.5 — Timeout del cobot (caso de error)

**Acción:** Publicar el AMR (A.1) pero **no** responder con FINISHED. Esperar 60 s.

**Log ESP32:**
```
I (...) demo_integracion::logic_task: [ESC1] Timeout esperando FINISHED — abortando ciclo
```

El sistema NO publica en `db/push`. El bucle vuelve a ciclos de ESC2 hasta el próximo ARRIVED.

---

## Bloque B — Escenario 2: DB → RoboDK → Cámara

### B.1 — Consulta automática de lote

Al arrancar (o cuando no hay actividad de cobot), el ESP32 publica en `giirob/pr2-A1/db/pull`:

```json
{ "query": "lote_pendiente" }
```

**Log bridge:**
```
INFO bridge_demo: Mensaje en [giirob/pr2-A1/db/pull]: {"query":"lote_pendiente"}
INFO bridge_demo: Lote pendiente enviado: L0001 (3 tapas)
```

**Topic `giirob/pr2-A1/db/pull/response` recibe:**

```json
{
  "color":    "red",
  "lote_id":  "L0001",
  "quantity": 3
}
```

**Log ESP32:**
```
I (...) demo_integracion::mqtt_manager: db/pull/response: {"color":"red","lote_id":"L0001","quantity":3}
I (...) demo_integracion::logic_task: [ESC2] Lote obtenido: id=L0001 color=red cantidad=3
```

---

### B.2 — Spawn a RoboDK

**Topic `giirob/pr2-A1/devices/robodk/action` recibe:**

```json
{
  "cap_id":  "C0001",
  "cmd":     "spawn",
  "color":   "red",
  "device":  "ESP32-S3",
  "lote_id": "L0001"
}
```

**Log ESP32:**
```
I (...) demo_integracion::mqtt_manager: Publicado en [giirob/pr2-A1/devices/robodk/action]: {"cap_id":"C0001",...}
I (...) demo_integracion::logic_task: [ESC2] Spawn enviado a RoboDK — cap_id=C0001
```

**En RoboDK (visual):** aparece un objeto `C0001` de color rojo sobre `Frame Cinta`.

---

### B.3 — Confirmación de cámara y registro en BD

**Topic `giirob/pr2-A1/devices/camera/data` recibe** (publicado por Python/RoboDK):

```json
{
  "x":         <posición X en la escena RoboDK>,
  "y":         <posición Y en la escena RoboDK>,
  "color":     "red",
  "precision": 0.99,
  "cap_id":    "C0001",
  "lote_id":   "L0001"
}
```

> Las coordenadas `x` e `y` dependen de dónde RoboDK coloque la tapa en la escena y varían cada ciclo.

**Log ESP32:**
```
I (...) demo_integracion::mqtt_manager: Camara detectó tapa: {"x":...,"y":...,"color":"red",...}
I (...) demo_integracion::logic_task: [ESC2] Camara confirmó cap_id=C0001 color=red pos=(X.X,Y.Y)
I (...) demo_integracion::mqtt_manager: Publicado en [giirob/pr2-A1/db/push]: {"cap_id":"C0001","event":"tapa_clasificada","lote_id":"L0001"}
I (...) demo_integracion::logic_task: [ESC2] tapa_clasificada enviada — lote=L0001 cap=C0001
```

**Log bridge:**
```
INFO bridge_demo: Mensaje en [giirob/pr2-A1/db/push]: {"cap_id":"C0001","event":"tapa_clasificada","lote_id":"L0001"}
INFO bridge_demo: Tapa clasificada en lote L0001 (1 filas)
```

**Verificar en BD** (después de 1 tapa):
```sql
SELECT lote_id, total_tapas_entrada, total_tapas_clasificadas
FROM   material_no_clasificado;
```
```
 lote_id | total_tapas_entrada | total_tapas_clasificadas
---------+---------------------+-------------------------
 L0001   |                   3 |                        1
 L0002   |                   3 |                        0
```

---

### B.4 — Lotes completados y reset automático

Cuando todos los lotes alcanzan `total_tapas_clasificadas = total_tapas_entrada`, el bridge los resetea automáticamente y el ESP32 reanuda el ciclo.

**Log bridge** al recibir la última consulta sin lotes:
```
INFO bridge_demo: Demo reset: 2 lotes reiniciados a clasificadas=0
WARN bridge_demo: Todos los lotes completados — demo reiniciado automáticamente
```

**Topic `giirob/pr2-A1/db/pull/response` recibe:**
```json
{ "lote_id": null }
```

**Log ESP32:**
```
W (...) demo_integracion::logic_task: [ESC2] Sin lotes pendientes — reintentando en 60 s
```

Tras 30 s el ESP32 consulta de nuevo y recibe L0001 con `quantity:3` (ya reseteado).

> No es necesario restaurar la BD manualmente entre ejecuciones.

---

### B.5 — Timeout de cámara (caso de error)

**Acción:** No tener Python corriendo en RoboDK y esperar 15 s tras el spawn.

**Log ESP32:**
```
E (...) demo_integracion::logic_task: [ESC2] Timeout esperando confirmación de cámara — continuando
```

El bucle continúa al siguiente ciclo sin bloquearse.

---

## Bloque C — Pruebas manuales del bridge

### C.1 — Query de operarios desde MQTT Explorer

**Publicar** en `giirob/pr2-A1/db/pull`:
```json
{ "query": "operarios" }
```

**Topic `giirob/pr2-A1/db/pull/response` recibe:**
```json
{
  "operarios": [
    { "operario_id": 1, "nombre": "Carlos", "apellido": "Martinez" },
    { "operario_id": 2, "nombre": "Laura",  "apellido": "Gomez"    },
    { "operario_id": 3, "nombre": "Miguel", "apellido": "Lopez"    }
  ]
}
```

**Log bridge:**
```
INFO bridge_demo: Operarios enviados: 3 registros
```

---

### C.2 — Query de lote desde MQTT Explorer

**Publicar** en `giirob/pr2-A1/db/pull`:
```json
{ "query": "lote_pendiente" }
```

**Topic `giirob/pr2-A1/db/pull/response` recibe:**
```json
{
  "color":    "red",
  "lote_id":  "L0001",
  "quantity": 3
}
```

**Log bridge:**
```
INFO bridge_demo: Lote pendiente enviado: L0001 (3 tapas)
```

---

### C.3 — JSON malformado en db/push

**Publicar** en `giirob/pr2-A1/db/push`:
```
esto no es json
```

**Log bridge:**
```
ERROR bridge_demo: JSON invalido en db/push: esto no es json
```

El bridge continúa sin crash.

---

### C.4 — Query desconocida en db/pull

**Publicar** en `giirob/pr2-A1/db/pull`:
```json
{ "query": "algo_desconocido" }
```

**Log bridge:**
```
WARN bridge_demo: db/pull query desconocida: algo_desconocido
```

No hay respuesta en `db/pull/response`.

---

## Resumen de topics

| Topic | Dirección | Escenario |
|-------|-----------|-----------|
| `giirob/pr2-A1/devices/amr/status` | AMR → ESP32 | 1 |
| `giirob/pr2-A1/devices/cobot/action` | ESP32 → Cobot | 1 |
| `giirob/pr2-A1/devices/cobot/status` | Cobot → ESP32 | 1 |
| `giirob/pr2-A1/db/pull` | ESP32 → Bridge | 1 y 2 |
| `giirob/pr2-A1/db/pull/response` | Bridge → ESP32 | 1 y 2 |
| `giirob/pr2-A1/db/push` | ESP32 → Bridge | 1 y 2 |
| `giirob/pr2-A1/devices/robodk/action` | ESP32 → RoboDK | 2 |
| `giirob/pr2-A1/devices/camera/data` | RoboDK → ESP32 | 2 |
