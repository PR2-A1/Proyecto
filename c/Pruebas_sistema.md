# GIIROB — Pruebas de integración del sistema completo

Guía de pruebas manuales end-to-end. Cubre el ESP32, el bridge Rust, el bridge Python/RoboDK y la base de datos PostgreSQL.

---

## Prerrequisitos

Verificar que todos los servicios están activos antes de comenzar:

| Servicio | Cómo arrancarlo | Señal de OK |
|---|---|---|
| PostgreSQL | `pg_ctl start` / servicio Windows | `psql -U postgres -c "\l"` muestra la BD |
| Bridge Rust | `cd mqtt_db_bridge && cargo run` | Línea `Bridge listo, esperando mensajes...` |
| Bridge Python | `cd python_bridge && python MqttListener.py` | Línea `pick_worker iniciado` |
| RoboDK | Abrir la escena `.rdk` | Delta presente, targets y `cap_template` visibles |
| ESP32 | Flasheado y alimentado | LED de estado, conexión Wi-Fi activa |

Para monitorizar todos los mensajes MQTT del sistema en tiempo real:
```bash
mosquitto_sub -h broker.hivemq.com -t "giirob/pr2-A1/#" -v
```

Para publicar mensajes de prueba:
```bash
mosquitto_pub -h broker.hivemq.com -t "<topic>" -m '<json>'
```

---

## Datos previos — insertar antes de empezar

```sql
INSERT INTO proveedor (num_proveedor, cif_nif, nombre, certificacion_iso) VALUES
('P0001', 'B12345678', 'Tapas García S.L.',       true),
('P0002', 'A87654321', 'Plásticos Roca S.A.',     false),
('P0003', 'B11223344', 'Industrias Molina',        true),
('P0004', 'A99887766', 'Suministros Vega S.L.',   true),
('P0005', 'B55443322', 'Componentes del Sur S.A.', false);

INSERT INTO operario (operario_id, nombre, apellido) VALUES
(1, 'Carlos',   'Martínez'),
(2, 'Laura',    'Sánchez'),
(3, 'Miguel',   'Torres'),
(4, 'Ana',      'Romero'),
(5, 'Fernando', 'Jiménez');
```

---

## Restricciones del esquema

- `caja_id`, `lote_id`, `proveedor` → `CHAR(5)`, máximo 5 caracteres.
- `color` en `caja` → solo acepta: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `WHITE`.
- `proveedor` en `proveedor_material` → FK a `proveedor`, debe existir antes.
- `lotes` en `box_completed` → FK a `material_no_clasificado`, el lote debe existir antes.
- `operario_cierre_id` en `palet` → FK a `operario`, debe existir antes.

---

## Bloque 1 — Conectividad y estado del sistema

### 1.1 Solicitar estado completo
<!-- Funciona correctamente -->
**Topic:** `giirob/pr2-A1/devices/scada/action`
```json
{ "cmd": "status" }
```

**Verificar en:** `giirob/pr2-A1/devices/scada/status`

Respuesta esperada (campos clave):
```json
{
  "mode": "manual",
  "lote_id": null,
  "total_processed": 0,
  "auto_target": 0,
  "tolvas": { "TOLVA_1": 0, "TOLVA_2": 0, "TOLVA_3": 0, "TOLVA_4": 0, "TOLVA_5": 0, "TOLVA_6": 0 },
  "pallets": { "PALLET_1": 0, "PALLET_2": 0, "PALLET_3": 0, "PALLET_4": 0, "PALLET_5": 0, "PALLET_6": 0 }
}
```

---

### 1.2 Cambiar a modo Auto
<!-- Funciona correctamente -->
**Topic:** `giirob/pr2-A1/devices/scada/action`
```json
{ "cmd": "set_mode", "mode": "auto" }
```

Solicitar estado de nuevo (prueba 1.1) y verificar que `"mode": "auto"`.

---

### 1.3 Cambiar a modo Manual
<!-- Funciona correctamente -->
```json
{ "cmd": "set_mode", "mode": "manual" }
```

Verificar `"mode": "manual"` en la respuesta de estado.

---

### 1.4 Reset del sistema

```json
{ "cmd": "reset" }
```

**Verificar:** todos los contadores de tolvas y pallets a 0, `lote_id` limpio. El modo no cambia.

---

## Bloque 2 — Gestión de lotes (SCADA → Bridge → DB)

### 2.1 Crear lote con proveedor
<!-- Funciona correctamente -->
**Topic:** `giirob/pr2-A1/devices/scada/action`
```json
{ "cmd": "gen", "lote_id": "L0020", "proveedor": "P0001", "quantity": 200 }
```

**Verificar lote:**
<!-- Funciona correctamente -->
```sql
SELECT lote_id, total_tapas_entrada, fecha_inicio
FROM material_no_clasificado
WHERE lote_id = 'L0020';
-- Debe mostrar L0020, 200, fecha de hoy
```

**Verificar proveedor:**
<!-- Funciona correctamente -->
```sql
SELECT proveedor, lote_id FROM proveedor_material WHERE lote_id = 'L0020';
-- Debe mostrar P0001, L0020
```

---

### 2.2 Crear lote sin proveedor
<!-- Funciona correctamente -->
```json
{ "cmd": "gen", "lote_id": "L0021", "quantity": 50 }
```

```sql
SELECT lote_id FROM material_no_clasificado WHERE lote_id = 'L0021';
-- Debe existir

SELECT COUNT(*) FROM proveedor_material WHERE lote_id = 'L0021';
-- Debe devolver 0
```

---

### 2.3 Lote duplicado — quantity no cambia
<!-- Funciona correctamente -->
Publicar el mismo lote con cantidad distinta:
```json
{ "cmd": "gen", "lote_id": "L0020", "proveedor": "P0002", "quantity": 999 }
```

```sql
SELECT total_tapas_entrada FROM material_no_clasificado WHERE lote_id = 'L0020';
-- Debe seguir siendo 200, no 999
```

---

### 2.4 Alias de campo — `lote` en lugar de `lote_id`
<!-- Funciona correctamente -->
El bridge acepta ambas claves:
```json
{ "cmd": "gen", "lote": "L0022", "quantity": 10 }
```

```sql
SELECT lote_id FROM material_no_clasificado WHERE lote_id = 'L0022';
-- Debe existir
```

---

### 2.5 Payload inválido — sin quantity
<!-- Funciona correctamente -->
```json
{ "cmd": "gen", "lote_id": "L0099" }
```

**Verificar en los logs del bridge:** mensaje `gen sin lote_id o quantity inválido`.

```sql
SELECT COUNT(*) FROM material_no_clasificado WHERE lote_id = 'L0099';
-- Debe devolver 0
```

---

## Bloque 3 — Modo Manual (ESP32 + RoboDK)

### 3.1 Generar una tapa roja
<!-- Todavía no se sabe -->
Asegurarse de estar en modo Manual (prueba 1.3) y tener el lote activo.

**Topic:** `giirob/pr2-A1/devices/scada/action`
```json
{ "cmd": "gen", "lote_id": "L0020", "color": "red", "quantity": 1 }
```

**Secuencia esperada:**
1. ESP32 publica SPAWN en `robodk/action` → `{"cmd":"spawn","color":"red","cap_id":"cap_1"}`
2. Python bridge crea tapa roja en RoboDK, la posiciona en `spawn_point`
3. Python bridge publica en `camera/data` → `{"x":...,"y":...,"color":"red","precision":0.99,"cap_id":"cap_1"}`
4. ESP32 valida color (coincide con `red`) y publica PICK en `delta/action`
5. Python bridge ejecuta pick: aproximación → descenso → subida → tolva → home
6. SCADA publica confirmación en `scada/status` → `{"cmd":"done","cap_id":"cap_1","tolva":"TOLVA_1"}`
7. ESP32 incrementa `tolva_counts[0]`

---

### 3.2 Color incorrecto en modo Manual (tapa descartada)

Con `expected_color = "red"`, forzar una detección de cámara de color diferente publicando manualmente en `camera/data`:

**Topic:** `giirob/pr2-A1/devices/camera/data`
```json
{ "x": 10.5, "y": 8.2, "color": "blue", "precision": 0.98, "cap_id": "cap_X" }
```

**Verificar:** el ESP32 NO publica PICK (color no coincide). Monitorizar `delta/action` — no debe aparecer ningún mensaje.

---

### 3.3 Detección con precisión baja (descartada)

```json
{ "x": 10.5, "y": 8.2, "color": "red", "precision": 0.90, "cap_id": "cap_Y" }
```

**Verificar:** el ESP32 descarta la detección (precision ≤ 0.95). No se publica PICK.

---

## Bloque 4 — Modo Auto

### 4.1 Lote pequeño (6 tapas)
<!-- Revisar más tarde cuando esté robodk -->
Cambiar a modo Auto y lanzar lote:
```json
{ "cmd": "gen", "lote_id": "L0020", "quantity": 6 }
```

**Secuencia esperada:**
1. ESP32 genera 6 spawns en colores rotativos: red → green → yellow → blue → white → orange
2. Cada tapa aparece en RoboDK, es detectada por la "cámara" y clasificada por el Delta
3. Al completar las 6 tapas, ESP32 publica en `scada/status`:
```json
{ "event": "batch_complete", "total": 6, "lote_id": "L0020" }
```

**Verificar estado tras completar:**
```json
{ "cmd": "status" }
```
`auto_validated` debe ser 6, igual a `auto_target`.

---

### 4.2 Protección contra desbordamiento de tolva

Con el sistema en Auto, cuando `tolva_counts[i] >= 2` (umbral), el ESP32 deja de enviar PICKs para ese color hasta que el AMR vacíe la tolva.

**Verificar en logs del ESP32:** mensaje de rechazo de tapa por tolva llena.
**Verificar en `delta/action`:** no aparece PICK para la tolva saturada.

---

## Bloque 5 — Coordinación AMR

### 5.1 AMR enviado a tolva (automático)
<!-- Funciona correctamente -->
Cuando `tolva_counts[i] >= 2`, el ESP32 publica automáticamente:

**Verificar en `amr/action`:**
```json
{ "cmd": "goto", "location": "tolva_1" }
```

---

### 5.2 AMR llega a la tolva (simulado)
<!-- Funciona correctamente -->
**Topic:** `giirob/pr2-A1/devices/amr/status`
```json
{ "status": "arrived", "location": "TOLVA_1" }
```

**Verificar en logs del ESP32:** registra llegada, inicia espera de 10 s.
**Verificar en estado:** `amr_pending_tolva` y `amr_arrived_tolva` consistentes.

---

### 5.3 AMR enviado a cobot_pick (automático tras 10 s)
<!-- Funciona correctamente -->
Después de 10 s de la llegada, el ESP32 publica:

**Verificar en `amr/action`:**
```json
{ "cmd": "goto", "location": "cobot_pick" }
```

**Verificar en `db/push`:** se publica `BOX_COMPLETED`:
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "CXXXX",
  "color": "red",
  "codigo_etiqueta": "ETQXXXXXXX",
  "estado": true,
  "lotes": ["L0020"]
}
```

**Verificar en PostgreSQL:**
```sql
SELECT caja_id, color, estado, palet_id FROM caja ORDER BY caja_id DESC LIMIT 5;
```

---

### 5.4 AMR llega a cobot_pick (simulado)
<!-- Funciona correctamente -->
```json
{ "status": "arrived", "location": "cobot_pick" }
```

**Verificar:** `cobot_ready = true` (solicitar estado). El ESP32 enviará orden al Cobot.

---

### 5.5 AMR llega a tolva incorrecta (manejo de error)
<!-- Funciona correctamente -->
Enviar el AMR a `tolva_1` y simular llegada a `tolva_2`:

```json
{ "status": "arrived", "location": "TOLVA_2" }
```

**Verificar en logs del ESP32:** registra el error de tolva inesperada pero no bloquea el flujo.

---

## Bloque 6 — Coordinación Cobot y persistencia de pallet

### 6.1 Cobot paletiza — pallet abierto

Tras `cobot_ready = true`, el ESP32 envía `start` al Cobot. Simular finalización:

**Topic:** `giirob/pr2-A1/devices/cobot/status`
```json
{ "status": "finished", "id_pallet": 10 }
```

**Verificar en `db/push`:**
```json
{
  "event": "caja_paletizada",
  "caja_id": "CXXXX",
  "palet_id": 10,
  "codigo_palet": "PALET000001",
  "color_id": "RED",
  "estado": false
}
```

**Verificar en PostgreSQL:**
```sql
SELECT palet_id, codigo_palet, estado, operario_cierre_id FROM palet WHERE palet_id = 10;
-- operario_cierre_id debe ser NULL (pallet aún abierto)
-- Revisar porque el operario_cierre_id NO ESTÁ SACANDO NULL

SELECT caja_id, palet_id FROM caja WHERE palet_id = 10;
```

---

### 6.2 Cierre de pallet (12 cajas — operario asignado)

Tras 12 finalizaciones del Cobot para el mismo pallet, se activa el flujo de cierre:

**Secuencia esperada:**
1. ESP32 publica en `db/pull`:
```json
{ "query": "operarios" }
```
2. Bridge responde en `db/pull/response`:
```json
{ "operarios": [{"operario_id": 1, "nombre": "Carlos", "apellido": "Martínez"}, ...] }
```
3. ESP32 elige un operario y publica en `db/push`:
```json
{
  "event": "caja_paletizada",
  "caja_id": "CXXXX",
  "palet_id": 10,
  "codigo_palet": "PALET000001",
  "color_id": "RED",
  "estado": true,
  "operario_id": 3
}
```
4. ESP32 publica en `scada/status`:
```json
{ "event": "pallet_full", "palet_id": 10, "codigo_palet": "PALET000001" }
```

**Verificar en PostgreSQL:**
```sql
SELECT palet_id, estado, operario_cierre_id FROM palet WHERE palet_id = 10;
-- estado = true, operario_cierre_id entre 1 y 5

SELECT p.palet_id, p.estado, o.nombre, o.apellido
FROM palet p
JOIN operario o ON o.operario_id = p.operario_cierre_id
WHERE p.palet_id = 10;
```

---

### 6.3 Rotación de pallets

Tras cerrar el pallet 10, el siguiente `FINISHED` del Cobot debe dirigirse al pallet 11 (`pallet2`):

**Verificar en `cobot/action`:**
```json
{ "cmd": "start", "id_pallet": 11, "mode": "pallet", "pos": "pallet2" }
```

---

## Bloque 7 — Sistema de emergencia

### 7.1 Activar emergencia por MQTT

**Topic:** `giirob/pr2-A1/system/emergency/action`
```json
{ "cmd": "estop" }
```

**Verificar en `emergency/status`:**
```json
{ "status": "active", "device": "ESP32-S3", "sensor": "mqtt_action" }
```

**Verificar comportamiento:**
- El Python bridge descarta picks nuevos y vacía la cola de picks pendientes
- El ESP32 ignora comandos SCADA `action`
- LED de emergencia encendido (si hay hardware)

---

### 7.2 Comandos SCADA ignorados durante emergencia

Con emergencia activa, publicar:
```json
{ "cmd": "gen", "lote_id": "L0099", "quantity": 1 }
```

**Verificar:** el ESP32 NO procesa el spawn. No aparece ningún mensaje en `robodk/action`.

> El bridge Rust SÍ procesa el mensaje (crea el lote en DB), porque el bridge no tiene estado de emergencia — solo el ESP32.

---

### 7.3 Reanudar desde emergencia por MQTT

**Topic:** `giirob/pr2-A1/system/emergency/action`
```json
{ "cmd": "resume" }
```

**Verificar en `emergency/status`:**
```json
{ "status": "operative", "source": "ESP32-S3", "sensor": "mqtt_action" }
```

El Python bridge vuelve a aceptar picks.

---

### 7.4 Emergencia desde el AMR (colisión)

```json
{ "cmd": "estop", "source": "AMR", "reason": "collision" }
```

**Verificar:** mismo comportamiento que 7.1. El campo `source` y `reason` son informativos.

---

### 7.5 Pick encolado antes de emergencia (descartado)

1. Encolar un pick manualmente publicando en `delta/action`:
```json
{ "cmd": "pick", "x": 10.0, "y": 5.0, "color": "red", "tolva": "tolva_1", "cap_id": "cap_test" }
```
2. Inmediatamente activar emergencia (prueba 7.1).

**Verificar en logs del Python bridge:** mensaje `Emergencia: N pick(s) descartados de la cola`. El pick NO se ejecuta al reanudar.

---

## Bloque 8 — Bridge de base de datos (directo a `db/push`)

Pruebas aisladas del bridge Rust publicando directamente en los topics. No requieren ESP32 activo.

### 8.1 Registrar caja sin lotes

**Topic:** `giirob/pr2-A1/db/push`
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "T0001",
  "color": "green",
  "codigo_etiqueta": "ETQ9990001",
  "estado": true,
  "lotes": []
}
```

```sql
SELECT caja_id, color, codigo_etiqueta, estado, palet_id
FROM caja WHERE caja_id = 'T0001';
-- color=GREEN, palet_id=NULL
```

---

### 8.2 Registrar caja con lote

El lote `L0020` debe existir (prueba 2.1).

```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "T0002",
  "color": "blue",
  "codigo_etiqueta": "ETQ9990002",
  "estado": true,
  "lotes": ["L0020"]
}
```

```sql
SELECT lote_id, caja_id FROM material_caja WHERE caja_id = 'T0002';
-- Debe mostrar L0020, T0002
```

---

### 8.3 Actualizar caja — color y etiqueta cambian, `palet_id` no

Publicar un segundo `BOX_COMPLETED` para la misma caja:
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "T0001",
  "color": "yellow",
  "codigo_etiqueta": "ETQ9999999",
  "estado": false,
  "lotes": []
}
```

```sql
SELECT color, codigo_etiqueta, estado, palet_id FROM caja WHERE caja_id = 'T0001';
-- color=YELLOW, etiqueta=ETQ9999999, estado=false, palet_id=NULL (sin cambio)
```

---

### 8.4 Paletizar caja — pallet abierto

```json
{
  "event": "caja_paletizada",
  "caja_id": "T0001",
  "palet_id": 10,
  "codigo_palet": "PALET000010",
  "color_id": "YELLOW",
  "estado": false
}
```

```sql
SELECT palet_id FROM caja WHERE caja_id = 'T0001';                   -- 10
SELECT operario_cierre_id FROM palet WHERE palet_id = 10;            -- NULL
```

---

### 8.5 `palet_id` sobrevive a un segundo `BOX_COMPLETED`

Tras la prueba 8.4, publicar de nuevo:
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "T0001",
  "color": "orange",
  "codigo_etiqueta": "ETQ9999999",
  "estado": true,
  "lotes": []
}
```

```sql
SELECT palet_id FROM caja WHERE caja_id = 'T0001';
-- DEBE seguir siendo 10 — el ON CONFLICT no toca palet_id
```

---

### 8.6 Cerrar pallet con operario

```json
{
  "event": "caja_paletizada",
  "caja_id": "T0002",
  "palet_id": 10,
  "codigo_palet": "PALET000010",
  "color_id": "YELLOW",
  "estado": true,
  "operario_id": 2
}
```

```sql
SELECT estado, operario_cierre_id FROM palet WHERE palet_id = 10;
-- estado=true, operario_cierre_id=2
```

---

### 8.7 Cerrar pallet sin `operario_id` (warning, sin fallo)

```json
{
  "event": "caja_paletizada",
  "caja_id": "T0001",
  "palet_id": 11,
  "codigo_palet": "PALET000011",
  "color_id": "YELLOW",
  "estado": true
}
```

**Verificar en logs del bridge:** mensaje `Palet 11 cerrado sin operario_id`.

```sql
SELECT operario_cierre_id FROM palet WHERE palet_id = 11;
-- NULL — no se asignó
```

---

### 8.8 Consulta de operarios vía `db/pull`

**Topic:** `giirob/pr2-A1/db/pull`
```json
{ "query": "operarios" }
```

**Verificar en `db/pull/response`:**
```json
{
  "operarios": [
    {"operario_id": 1, "nombre": "Carlos",   "apellido": "Martínez"},
    {"operario_id": 2, "nombre": "Laura",    "apellido": "Sánchez"},
    {"operario_id": 3, "nombre": "Miguel",   "apellido": "Torres"},
    {"operario_id": 4, "nombre": "Ana",      "apellido": "Romero"},
    {"operario_id": 5, "nombre": "Fernando", "apellido": "Jiménez"}
  ]
}
```

---

### 8.9 JSON malformado (sin crash del bridge)

**Topic:** `giirob/pr2-A1/db/push`
```
esto no es json
```

**Verificar en logs del bridge:** mensaje de error JSON. El bridge sigue funcionando y procesa el siguiente mensaje correctamente.

---

## Limpieza de datos de prueba

```sql
UPDATE caja SET palet_id = NULL              WHERE caja_id IN ('T0001', 'T0002');
DELETE FROM palet                            WHERE palet_id IN (10, 11);
DELETE FROM material_caja                    WHERE caja_id IN ('T0001', 'T0002');
DELETE FROM caja                             WHERE caja_id IN ('T0001', 'T0002');
DELETE FROM proveedor_material               WHERE lote_id IN ('L0020', 'L0021', 'L0022');
DELETE FROM material_no_clasificado          WHERE lote_id IN ('L0020', 'L0021', 'L0022');
DELETE FROM operario                         WHERE operario_id IN (1, 2, 3, 4, 5);
DELETE FROM proveedor                        WHERE num_proveedor IN ('P0001','P0002','P0003','P0004','P0005');
```
