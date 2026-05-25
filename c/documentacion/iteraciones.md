# Iteraciones

## main — Flujo de arranque

Secuencia de inicialización del sistema. No es un loop — se ejecuta una sola vez de forma lineal. Cada paso depende del anterior: si Wi-Fi no conecta el sistema se bloquea, si MQTT falla propaga el error y main termina. El último paso es `emergency_task`, que toma el hilo principal y nunca retorna.

```
main()
  │
  ├─ Inicializa logger y parches del sistema
  ├─ Toma periféricos (pines, modem)
  ├─ Clona NVS para cada módulo que lo necesita
  ├─ Crea recursos compartidos:
  │     wifi_ready     → AtomicBool (Wi-Fi listo?)
  │     emergency_stop → AtomicBool (emergencia activa?)
  │     control_state  → Arc<Mutex<ControlState>>
  │     pull_slot      → Arc<Mutex<Option<SyncSender>>> (hueco consultas BD)
  │     event_tx/rx    → canal Core 0 → Core 1 (capacidad 64)
  │
  ├─ Lanza Wi-Fi y BLOQUEA hasta que conecta
  │     wifi_manager::spawn_wifi_manager(...)
  │     wifi_manager::wait_until_ready(&wifi_ready)  ← espera aquí
  │
  ├─ Carga tolva_counts desde NVS (si existen)
  │
  ├─ Crea cliente MQTT y registra callback (Core 0)
  │     mqtt_manager::connect_and_subscribe_with_state(...)
  │     → recibe event_tx para encolar eventos hacia Core 1
  │
  ├─ Lanza logic_task en hilo separado (Core 1)
  │     logic_task::spawn_logic_task(...)
  │     → recibe event_rx para consumir eventos de Core 0
  │
  └─ Entra en emergency_task — NUNCA RETORNA
        monitorea botones / LED / buzzer / MQTT
        loop infinito de 50ms
```

## emergency_task — Ciclo por iteración

Cada iteración del loop gestiona la detección de botones físicos y la sincronización del LED, buzzer y publicación MQTT. El hilo se duerme esperando una interrupción de botón o un timeout de 50ms, lo que ocurra primero. El timeout existe para detectar cambios de estado provocados por comandos MQTT aunque no haya pulsación física.

```
Iteración N:
  │
  ├─ Crea Notification + flags en stack
  ├─ Registra ISR (closures apuntan al stack de esta iteración)
  ├─ Duerme hasta 50ms ──────────────────────────────────────┐
  │                                                           │
  │   [Si botón pulsado]                                      │
  │   Hardware → ISR → flag=true → notify → despierta ───────┘
  │                                                           │
  │   [Si no pasa nada / comando MQTT]                        │
  │   Timeout 50ms ───────────────────────────────────────────┘
  │
  ├─ Lee flags → actualiza emergency_stop
  ├─ ¿Cambió estado? → LED / buzzer / MQTT
  └─ Stack destruido → vuelve al inicio
```

## logic_task — Ciclo por iteración

Cada iteración del loop gestiona la producción de tapas, los movimientos del AMR y el paletizado del cobot. El ciclo tiene período fijo de **500ms** (salvo emergencia activa donde colapsa a 100ms inactivo). Todas las publicaciones MQTT del sistema ocurren dentro de este ciclo — nunca desde el callback de Core 0.

```
Iteración N:
  │
  ├─ ¿emergency_stop == true?
  │     Sí → sleep 100ms → siguiente iteración (nada más se ejecuta)
  │     No → continúa ↓
  │
  ├─ Drena la cola de eventos (mpsc::try_recv en loop)
  │     DeltaCompleted { color, id_cap }
  │       → tolva_counts[color] += 1
  │       → total_processed += 1
  │       → si modo Auto: auto_validated += 1 → ¿lote completo? → batch_complete_pending = true
  │       → si modo Manual: manual_remaining -= 1
  │       → guarda tolva_counts en NVS
  │     AmrArrived { location }
  │       → si location == almacén: cobot_ready = true
  │       → si location == tolva_X: amr_arrived_tolva = index, registra timestamp
  │     CobotCompleted { id_pallet }
  │       → cobot_completed_event = Some(id_pallet)
  │       → cobot_in_progress = false
  │
  ├─ try_spawn_caps — genera tapas si no hay emergencia
  │     Modo AUTO y auto_spawned < auto_target:
  │       → color = get_random_color() (rotativo)
  │       → ¿tolva[color] < umbral? → publica robodk/action {"cmd":"spawn"} → auto_spawned += 1
  │     Modo MANUAL y manual_spawn_pending:
  │       → ¿tolva[color] < umbral? → publica robodk/action {"cmd":"spawn"} → pending = false
  │       → tolva llena: espera (log info) sin bloquear
  │
  ├─ handle_cobot_completed — gestiona fin de paletizado
  │     ¿cobot_completed_event.take()?
  │       Sí:
  │         → pallets[color].1 += 1 (incrementa caja en pallet)
  │         → ¿pallet lleno? → pallets[color].0 += 6 (siguiente ID), reinicia contador
  │         → query_operarios (si pallet lleno):
  │               publica db/pull {"query":"operarios"}
  │               espera db/pull/response hasta 5s (SyncSender temporal en PullSlot)
  │               elige operario aleatorio por nanosegundos del reloj
  │         → publica db/push {"event":"caja_paletizada", ...}
  │         → si pallet lleno: publica scada/status {"event":"pallet_full"}
  │       No: no hace nada
  │
  ├─ publish_status — toda la lógica de publicación MQTT
  │     Lee ControlState (lock) para recoger flags pendientes:
  │       status_requested       → publica scada/status (estado completo del sistema)
  │       batch_complete_pending → publica scada/status {"event":"batch_complete"}
  │       reset_db_pending       → publica db/push {"event":"reset"}
  │       tapas_clasificadas > 0 → publica db/push {"event":"tapa_clasificada"}
  │
  │     Lógica AMR:
  │       ¿AMR llegó a tolva y pasó el delay?
  │         → prepara caja (next_id_caja, next_etiqueta)
  │         → publica amr/action {"cmd":"goto", location:"ALMACEN"}
  │         → publica db/push {"event":"box_completed", ...}
  │         → resetea tolva_counts[tolva] = 0 → guarda NVS
  │       ¿AMR libre y tolva alcanzó umbral?
  │         → publica amr/action {"cmd":"goto", location:"TOLVA_X"}
  │         → registra amr_pending_tolva y timestamp despacho
  │       ¿AMR en camino > timeout?
  │         → error log → resetea amr_pending_tolva (anti-bloqueo)
  │
  │     Lógica cobot:
  │       ¿cobot_ready && !cobot_in_progress?
  │         → publica cobot/action {"cmd":"start", id_pallet, color, boxes_stacked}
  │         → cobot_in_progress = true, registra timestamp inicio
  │       ¿cobot en progreso > timeout?
  │         → error log → resetea cobot_in_progress (anti-bloqueo)
  │
  └─ sleep 500ms → siguiente iteración
```

**Invariante de diseño:** `logic_task` es el único punto del sistema que publica mensajes MQTT de salida. El callback de Core 0 solo encola intenciones en `ControlState` (flags como `status_requested`) y las deja pendientes para que `logic_task` las ejecute en su próxima iteración, cuando el cliente MQTT ya no está en uso.
