# GIIROB — Referencia de mensajes MQTT

Broker: `broker.hivemq.com:1883`

---

## Control SCADA ↔ ESP32

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"gen","id_lote":"L0042","quantity":100}` | Iniciar lote en modo Auto |
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"gen","id_lote":"L0042","color":"red","quantity":1}` | Generar tapa en modo Manual |
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"set_mode","mode":"auto"}` | Cambiar a modo Auto |
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"set_mode","mode":"manual"}` | Cambiar a modo Manual |
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"status"}` | Solicitar estado del sistema |
| `giirob/pr2-A1/devices/scada/action` | SCADA | ESP32 | `{"cmd":"reset"}` | Reiniciar contadores de tolvas y lote |
| `giirob/pr2-A1/devices/scada/status` | ESP32 | SCADA | `{"mode":"auto","id_lote":"L0042","total_processed":47,"tolvas":{...},"pallets":{...},...}` | Estado completo del sistema |
| `giirob/pr2-A1/devices/scada/status` | SCADA | ESP32 | `{"cmd":"done","id_cap":"C0005","tolva":"TOLVA_3"}` | Confirmar que Delta depositó la tapa en la tolva |
| `giirob/pr2-A1/devices/scada/status` | ESP32 | SCADA | `{"event":"batch_complete","total":100,...}` | Lote de producción completado |

> `id_lote` también acepta la clave `lote`. El campo `color` solo aplica en modo Manual.  
> El estado completo incluye: `mode`, `id_lote`, `total_processed`, `auto_target`, `auto_spawned`, `auto_validated`, `manual_remaining`, `expected_color`, `amr_pending_tolva`, `amr_arrived_tolva`, `amr_wait_seconds`, `pallets` (PALLET_1–6), `tolvas` (TOLVA_1–6).

---

## Visión y clasificación (Cámara → Delta)

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/devices/camera/data` | Cámara | ESP32 | `{"x":1.2,"y":3.4,"color":"red","precision":0.97,"id_cap":"C0001"}` | Tapa detectada en el campo visual |
| `giirob/pr2-A1/devices/delta/action` | ESP32 | Delta | `{"cmd":"pick","x":1.2,"y":3.4,"color":"red","tolva":"tolva_1","id_cap":"C0001","reason":"..."}` | Recoger tapa y depositarla en la tolva indicada |

> Las detecciones con `precision` ≤ 0.95 se ignoran.  
> El `id_cap` siempre está presente — lo genera el ESP32 en el spawn y RoboDK lo reenvía en la detección de cámara.  
> No se envía `pick` si la tolva ya tiene `tolva_counts + pending ≥ umbral` (protección de rebalsamiento).

---

## Generación de tapas (RoboDK)

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/devices/robodk/action` | ESP32 | RoboDK | `{"cmd":"spawn","color":"blue","id_cap":"C0042"}` | Generar tapa en la simulación |

> En modo Auto el color rota cíclicamente: `red → green → yellow → blue → white → orange → …`  
> El ESP32 genera el `id_cap` antes del spawn; RoboDK lo incluye en la detección de cámara para trazabilidad completa.

---

## AMR

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/devices/amr/action` | ESP32 | AMR | `{"cmd":"goto","location":"TOLVA_1"}` | Enviar AMR a recoger caja de la tolva llena |
| `giirob/pr2-A1/devices/amr/action` | ESP32 | AMR | `{"cmd":"goto","location":"cobot_pick"}` | Llevar caja al área del cobot tras espera de 10 s |
| `giirob/pr2-A1/devices/amr/status` | AMR | ESP32 | `{"status":"arrived","location":"TOLVA_1"}` | AMR llegó a la tolva — inicia espera de 10 s |
| `giirob/pr2-A1/devices/amr/status` | AMR | ESP32 | `{"status":"arrived","location":"cobot_pick"}` | AMR llegó al área del cobot — activa secuencia de paletizado |
| `giirob/pr2-A1/devices/amr/status` | AMR | SCADA | `{"status":"active","location":"TOLVA_1"}` | AMR operativo en la posición indicada |
| `giirob/pr2-A1/devices/amr/status` | AMR | SCADA | `{"status":"inactive","location":"TOLVA_1"}` | AMR inactivo o detenido |

> `location` válidos: `TOLVA_1`–`TOLVA_6` y `cobot_pick`.  
> El ESP32 solo procesa mensajes con `status: "arrived"`; los estados `active`/`inactive` son informativos para el SCADA.

---

## Cobot

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/devices/cobot/action` | ESP32 | Cobot | `{"cmd":"start","id_pallet":"P0001","color":"red","boxes_stacked":0}` | Ordenar al cobot paletizar la caja en el pallet indicado |
| `giirob/pr2-A1/devices/cobot/status` | Cobot | ESP32 | `{"status":"completed","id_pallet":"P0001"}` | Caja depositada correctamente en el pallet |

> `id_pallet` arranca en `P0001` e incrementa indefinidamente. Cada pallet se cierra al alcanzar `PALLET_CAPACITY` (12 cajas).

---

## Emergencia

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/system/emergency/action` | Cualquiera | ESP32 | `{"cmd":"estop","source":"SCADA"}` | Activar parada de emergencia |
| `giirob/pr2-A1/system/emergency/action` | Cualquiera | ESP32 | `{"cmd":"resume","source":"SCADA"}` | Reanudar sistema tras resolver la emergencia |
| `giirob/pr2-A1/system/emergency/action` | AMR | ESP32 | `{"cmd":"estop","source":"AMR","reason":"collision"}` | Emergencia iniciada por el propio AMR |
| `giirob/pr2-A1/system/emergency/action` | COBOT | ESP32 | `{"cmd":"estop","source":"COBOT","reason":"joint_limit"}` | Emergencia iniciada por el cobot |
| `giirob/pr2-A1/system/emergency/action` | DELTA | ESP32 | `{"cmd":"estop","source":"DELTA"}` | Emergencia iniciada por el delta |
| `giirob/pr2-A1/system/emergency/status` | ESP32 | Todos | `{"status":"emergency_active","source":"emergency_button"}` | Emergencia activa — sistema detenido |
| `giirob/pr2-A1/system/emergency/status` | ESP32 | Todos | `{"status":"emergency_inactive","source":"SCADA"}` | Emergencia desactivada — sistema reanudado |

> `sensor` indica el origen: `"emergency_button"` (GPIO38), `"resume_button"` (GPIO39) o `"mqtt_action"` (comando MQTT).

---

## Base de datos (Bridge MQTT-DB)

### Escritura — `db/push`

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/db/push` | ESP32 | Bridge | `{"event":"box_completed","id_caja":"B0012","color":"red","codigo_etiqueta":"ETQ0000003","estado":true,"lotes":["L0042"]}` | Persistir caja completada en PostgreSQL |
| `giirob/pr2-A1/db/push` | ESP32 | Bridge | `{"event":"caja_paletizada","id_caja":"B0012","id_palet":"P0001","id_color":"RED","estado":false}` | Vincular caja a pallet (pallet aún abierto) |
| `giirob/pr2-A1/db/push` | ESP32 | Bridge | `{"event":"caja_paletizada","id_caja":"B0012","id_palet":"P0001","id_color":"RED","estado":true,"id_operario":"OP003"}` | Vincular caja y cerrar pallet (12 cajas); ESP32 indica el operario de cierre |
| `giirob/pr2-A1/devices/scada/status` | ESP32 | SCADA | `{"event":"pallet_full","id_palet":"P0001"}` | Aviso al operario de que el pallet está lleno |
| `giirob/pr2-A1/devices/scada/action` | SCADA | Bridge | `{"cmd":"gen","id_lote":"L0042","quantity":500}` | Registrar nuevo lote en PostgreSQL |
| `giirob/pr2-A1/devices/scada/action` | SCADA | Bridge | `{"cmd":"gen","id_lote":"L0042","proveedor":"P0003","quantity":500}` | Registrar lote con proveedor en PostgreSQL |

### Consulta — `db/pull` / `db/pull/response`

| Topic | Emisor | Receptor | Mensaje | Motivo |
|---|---|---|---|---|
| `giirob/pr2-A1/db/pull` | ESP32 | Bridge | `{"query":"operarios"}` | ESP32 solicita la lista de operarios para elegir el de cierre |
| `giirob/pr2-A1/db/pull/response` | Bridge | ESP32 | `{"operarios":[{"id_operario":"OP001","nombre":"Carlos","apellido":"Martínez"},…]}` | Bridge responde con todos los operarios de la BD |

> El ESP32 recibe la lista, escoge un operario y lo envía como `id_operario` en el evento `caja_paletizada`.  
> El campo `color` se almacena en mayúsculas en la base de datos (`RED`, `BLUE`, etc.).  
> `codigo_etiqueta` tiene formato `ETQ0000001` (CHAR 10).
