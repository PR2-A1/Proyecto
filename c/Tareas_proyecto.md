# GIIROB — Tareas del proyecto

Desglose de componentes y tareas de implementación del sistema PR2.

---

## 1. Resumen de componentes

| Componente | Tecnología | Estado |
|---|---|---|
| Firmware ESP32-S3 | Rust (esp-idf-svc) | En desarrollo |
| Bridge MQTT-DB | Rust (tokio, rumqttc, tokio-postgres) | Implementado |
| Bridge Python-RoboDK | Python (paho-mqtt, robodk) | Implementado |
| Base de datos | PostgreSQL | Esquema definido |
| Documentación | Markdown | En progreso |

---

## 2. Diagrama de dependencias entre componentes

```mermaid
flowchart TD
    WiFi["WiFi Manager\nwifi_connection.rs\nwifi_manager.rs"]
    MQTT["MQTT Manager\nmqtt_manager.rs"]
    Vision["Vision Task\nvision_task.rs"]
    Logic["Logic Task\nlogic_task.rs"]
    Emergency["Emergency Task\nemergency_task.rs"]
    State["Control State\ncontrol_state.rs"]
    Config["Configuración\nconfig.rs"]

    BridgeRust["Bridge Rust\nmain.rs"]
    BridgePy["Bridge Python\nMqttListener.py\nRobotController.py\nconfig.py"]
    DB[("PostgreSQL\ngiirob")]

    Config --> WiFi
    Config --> MQTT
    Config --> Logic
    WiFi --> MQTT
    MQTT --> Vision
    MQTT --> Logic
    MQTT --> Emergency
    Vision --> Logic
    Logic --> State
    Vision --> State
    Emergency --> State
    MQTT --> State

    Logic -->|db/push\ndb/pull| BridgeRust
    BridgeRust --> DB
    Logic -->|robodk/action| BridgePy
    Logic -->|delta/action| BridgePy
```

---

## 3. Tareas por componente

### 3.1 Firmware ESP32-S3

```mermaid
flowchart TD
    subgraph Firmware["Firmware ESP32-S3"]
        F1["config.rs\nConstantes del sistema"]
        F2["wifi_connection.rs\nConexión WPA2 + FastScan"]
        F3["wifi_manager.rs\nReconexión automática"]
        F4["mqtt_manager.rs\nCliente MQTT + despacho"]
        F5["control_state.rs\nEstado compartido Arc/Mutex"]
        F6["vision_task.rs\nFiltrado precision + VisionSample"]
        F7["logic_task.rs\nBucle principal 500ms\nSpawn · Validación · AMR · Cobot · DB"]
        F8["emergency_task.rs\nGPIO + ISR + MQTT"]
        F9["nvs.rs\nPersistencia tolva_counts"]
    end

    F1 --> F2 & F3 & F4 & F6 & F7 & F8
    F2 --> F3 --> F4
    F4 --> F6 & F7 & F8
    F5 --> F6 & F7 & F8 & F4
    F7 --> F9
```

#### Subtareas pendientes en `logic_task.rs`

| Subtarea | Descripción |
|---|---|
| Generación de `cap_id` | Contador incremental: `cap_1`, `cap_2`, ... |
| Spawn en Auto | Rotación cíclica 6 colores, throttle por `auto_target` |
| Spawn en Manual | Un spawn por comando, validación estricta de color |
| Mapeado color → tolva | red→0, yellow→1, green→2, white→3, orange→4, blue→5 |
| Protección tolva llena | `tolva_counts[i] + pending[i] >= AMR_TOLVA_THRESHOLD` |
| Envío AMR a tolva | Cuando `tolva_counts[i] >= umbral` |
| Espera 10 s post-llegada | Timer con `Instant::now()` |
| Envío AMR a cobot_pick | Tras timeout, junto con `BOX_COMPLETED` |
| Envío orden Cobot | Cuando `cobot_ready && !cobot_in_progress` |
| Rotación de pallets | Índice cíclico 0..5 → id_pallet 10..15 |
| Cierre de pallet | `pallet_counts[i] >= PALLET_CAPACITY` |
| Solicitud operarios (`db/pull`) | Publicar query, suscribirse a respuesta |
| Selección aleatoria de operario | Elegir del array recibido |
| Publicar `caja_paletizada` | Con `estado: true/false` y `operario_id` |
| Publicar `pallet_full` | Al SCADA cuando se cierra un pallet |
| Publicar `batch_complete` | Al completar el lote en modo Auto |
| Publicar estado completo | En respuesta a `status` del SCADA |

---

### 3.2 Bridge Rust (mqtt_db_bridge)

```mermaid
flowchart LR
    subgraph Bridge["Bridge Rust"]
        B1["main.rs\nLoop principal MQTT"]
        B2["parse_box_completed_event()\nBoxCompletedEvent struct"]
        B3["parse_gen_command()\nGenCommand struct"]
        B4["parse_caja_paletizada()\nCajaPaletizadaEvent struct"]
        B5["Handler db/push\neventos de escritura"]
        B6["Handler db/pull\nconsultas y respuestas"]
        B7["Handler scada/action\ncmd: gen"]
        B8["Statements SQL\npreparados al arrancar"]
        B9["#[cfg(test)]\n6 tests unitarios"]
    end

    B1 --> B5 & B6 & B7
    B5 --> B2 & B4
    B7 --> B3
    B2 & B3 & B4 --> B9
    B5 & B6 & B7 --> B8
```

#### Statements SQL implementados

| Statement | Operación |
|---|---|
| `insert_caja_stmt` | INSERT caja ON CONFLICT DO UPDATE (sin palet_id) |
| `insert_material_caja_stmt` | INSERT material_caja ON CONFLICT DO NOTHING |
| `insert_lote_stmt` | INSERT material_no_clasificado ON CONFLICT DO NOTHING |
| `insert_proveedor_material_stmt` | INSERT proveedor_material ON CONFLICT DO NOTHING |
| `upsert_palet_stmt` | INSERT palet ON CONFLICT DO UPDATE (estado) |
| `link_caja_palet_stmt` | UPDATE caja SET palet_id |
| `set_operario_cierre_stmt` | UPDATE palet SET operario_cierre_id |

---

### 3.3 Bridge Python (python_bridge)

```mermaid
flowchart TD
    subgraph Python["Bridge Python"]
        ML["MqttListener.py\nEntrada MQTT\nloop_forever()"]
        RC["RobotController.py\nLógica RoboDK"]
        CF["config.py\nTopics, targets, colores, timeouts"]

        subgraph RC_detail["RobotController — funciones"]
            HS["_handle_spawn()\nhilo daemon por spawn"]
            HP["_handle_pick()\nencola en pick_queue"]
            HE["_handle_emergency()\nactiva / desactiva flag"]
            PW["_pick_worker()\nhilo consumidor daemon"]
            EP["_execute_pick()\nMoveJ/MoveL secuencia"]
        end
    end

    RDK["RoboDK\nAPI Python"]

    ML --> RC
    RC --> CF
    RC --> HS & HP & HE
    HP --> PW --> EP
    HS & EP --> RDK
```

#### Estado de issues Python

| Issue | Descripción | Estado |
|---|---|---|
| Race condition Copy/Paste | `_rdk_lock` protege RDK.Copy+Paste | Corregido |
| Cola no vaciada en emergencia | `_set_emergency(True)` drena `pick_queue` | Corregido |
| z hardcoded en pick | `config.PICK_Z` configurable | Corregido |
| Imports innecesarios en MqttListener | Eliminados `robolink`/`robomath` | Corregido |
| `COLOR_TOLVA_MAP` sin usar | Eliminado de config.py | Corregido |

---

## 4. Esquema de base de datos

```mermaid
erDiagram
    proveedor {
        CHAR5   num_proveedor PK
        VARCHAR cif_nif
        VARCHAR nombre
        BOOLEAN certificacion_iso
    }

    material_no_clasificado {
        CHAR5   lote_id PK
        DATE    fecha_inicio
        DATE    fecha_fin
        INT     total_tapas_entrada
        INT     total_tapas_clasificadas
        VARCHAR observaciones
    }

    proveedor_material {
        CHAR5 proveedor PK
        CHAR5 lote_id   PK
    }

    caja {
        CHAR5   caja_id PK
        VARCHAR color
        CHAR10  codigo_etiqueta
        BOOLEAN estado
        INT     palet_id
    }

    material_caja {
        CHAR5 lote_id PK
        CHAR5 caja_id PK
    }

    palet {
        INT     palet_id PK
        VARCHAR codigo_palet
        VARCHAR color_id
        BOOLEAN estado
        INT     operario_cierre_id
    }

    operario {
        INT     operario_id PK
        VARCHAR nombre
        VARCHAR apellido
    }

    proveedor ||--o{ proveedor_material : "suministra"
    material_no_clasificado ||--o{ proveedor_material : "tiene"
    material_no_clasificado ||--o{ material_caja : "contiene"
    caja ||--o{ material_caja : "agrupa"
    caja }o--|| palet : "pertenece a"
    operario ||--o{ palet : "cierra"
```

---

## 5. Flujo de mensajes MQTT por fase del sistema

```mermaid
gantt
    title Secuencia de mensajes en un ciclo completo (tapa → pallet cerrado)
    dateFormat  X
    axisFormat  %s s

    section Generación
    SCADA gen          :milestone, 0, 0
    ESP32 spawn        :1, 2
    RoboDK crea tapa   :2, 4

    section Clasificación
    camera/data        :milestone, 4, 4
    ESP32 valida       :4, 5
    delta/action pick  :5, 6
    Delta mueve tapa   :6, 10
    SCADA done         :milestone, 10, 10

    section AMR (2 tapas por tolva)
    amr/action goto tolva  :10, 11
    AMR en tránsito        :11, 14
    amr/status arrived     :milestone, 14, 14
    ESP32 espera 10s       :14, 24
    amr/action cobot_pick  :24, 25
    db/push BOX_COMPLETED  :24, 25

    section Cobot
    AMR en tránsito cobot  :25, 28
    amr/status arrived     :milestone, 28, 28
    cobot/action start     :28, 29
    Cobot paletiza         :29, 35
    cobot/status finished  :milestone, 35, 35

    section Cierre pallet (12 cajas)
    db/pull operarios      :35, 36
    db/pull/response       :36, 37
    db/push caja_paletizada:37, 38
    scada/status pallet_full:milestone, 38, 38
```

---

## 6. Checklist de entrega

### Firmware ESP32
- [ ] wifi_manager: reconexión automática verificada
- [ ] mqtt_manager: despacho de todos los topics documentados
- [ ] vision_task: filtro de precisión y `cap_id` validado
- [ ] logic_task: flujo completo Auto y Manual
- [ ] logic_task: coordinación AMR y Cobot
- [ ] logic_task: publicación `db/push` y `db/pull`
- [ ] emergency_task: botones físicos + MQTT
- [ ] NVS: persistencia de tolva_counts entre reinicios

### Bridge Rust
- [x] Parsers tipados con structs
- [x] Tests unitarios (6 casos)
- [x] Handler `db/push` (box_completed, caja_paletizada)
- [x] Handler `db/pull` (operarios → response)
- [x] Handler `scada/action` (gen)
- [x] ON CONFLICT correcto (sin borrar palet_id)

### Bridge Python
- [x] MqttListener separado de RobotController
- [x] Spawn con cap_id del ESP32
- [x] Lock en Copy/Paste RoboDK
- [x] Pick queue productor-consumidor
- [x] Emergencia: vaciado de cola
- [x] PICK_Z configurable
- [ ] Ajuste de PICK_Z según la escena real
- [ ] Ajuste de targets en config.py según escena real

### Base de datos
- [ ] Esquema creado y verificado
- [ ] Proveedores y operarios de prueba insertados
- [ ] FKs verificadas (proveedor, lote, operario)

### Documentación
- [x] SISTEMA.md actualizado
- [x] mqtt_messages.md actualizado
- [x] Pruebas.md (bridge)
- [x] Pruebas_sistema.md (sistema completo)
- [x] Diagramas_flujo.md
- [x] Tareas_proyecto.md
