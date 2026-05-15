# GIIROB — Diagramas de flujo

---

## 1. Arquitectura general del sistema

```mermaid
flowchart LR
    SCADA["SCADA\n(Operador)"]
    ESP32["ESP32-S3\n(Controlador central)"]
    RoboDK["RoboDK\n(Simulación)"]
    Camera["Cámara\n(Visión)"]
    Delta["Robot Delta\n(Clasificador)"]
    AMR["AMR\n(Transporte)"]
    Cobot["Cobot\n(Paletizador)"]
    Bridge["Bridge Rust\n(MQTT → DB)"]
    PythonBridge["Bridge Python\n(MQTT → RoboDK)"]
    DB[("PostgreSQL")]

    SCADA -->|scada/action| ESP32
    ESP32 -->|scada/status| SCADA

    ESP32 -->|robodk/action| PythonBridge
    PythonBridge -->|camera/data| ESP32
    PythonBridge <--> RoboDK

    ESP32 -->|delta/action| Delta
    Camera -->|camera/data| ESP32

    ESP32 -->|amr/action| AMR
    AMR -->|amr/status| ESP32

    ESP32 -->|cobot/action| Cobot
    Cobot -->|cobot/status| ESP32

    ESP32 <-->|emergency/action\nemergency/status| SCADA

    ESP32 -->|db/push| Bridge
    ESP32 <-->|db/pull\ndb/pull/response| Bridge
    Bridge --> DB
```

---

## 2. Ciclo de vida completo de una tapa

```mermaid
sequenceDiagram
    participant SCADA
    participant ESP32
    participant PythonBridge as Python Bridge (RoboDK)
    participant ESP32v as ESP32 vision-task
    participant Delta

    SCADA->>ESP32: gen (id_lote, color, quantity)
    Note over ESP32: Genera id_cap único ("C0042")
    ESP32->>PythonBridge: spawn {cmd, color, id_cap}
    PythonBridge->>PythonBridge: RDK.Copy+Paste → crea tapa en escena
    PythonBridge->>ESP32v: camera/data {x, y, color, precision, id_cap}

    alt precision > 0.95
        ESP32v->>ESP32: VisionSample (canal interno)
        Note over ESP32: Valida color según modo
        alt color válido y tolva con espacio
            ESP32->>Delta: pick {x, y, color, tolva, id_cap}
            Delta->>Delta: Mueve tapa a tolva
            SCADA->>ESP32: done {id_cap, tolva}
            Note over ESP32: tolva_counts[i]++ · guarda NVS
        else tolva llena o color incorrecto
            Note over ESP32: Descarta tapa — no envía PICK
        end
    else precision ≤ 0.95
        Note over ESP32v: Detección descartada
    end
```

---

## 3. Flujo completo de una caja (AMR + Cobot + DB)

```mermaid
flowchart TD
    A["tolva_counts[i] ≥ 2\n(umbral alcanzado)"]
    B["ESP32 genera id_caja\namr_pending_tolva = i"]
    C["Publica goto tolva_N → AMR"]
    D["AMR publica ARRIVED\nlocation: TOLVA_N"]
    E["ESP32 registra llegada\ninicia espera 10 s"]
    F["Timeout 10 s alcanzado"]
    G["Publica goto cobot_pick → AMR\nPublica BOX_COMPLETED → db/push\ntolva_counts[i] = 0"]
    H["Bridge Rust\ninserta caja en PostgreSQL\ninserta material_caja"]
    I["AMR publica ARRIVED\nlocation: cobot_pick"]
    J["cobot_ready = true"]
    K["ESP32 publica start → Cobot\ncobot_in_progress = true"]
    L["Cobot publica completed\nid_pallet: N"]
    M{"current_pallet_count ≥ PALLET_CAPACITY?"}
    N["ESP32 publica db/pull\nquery: operarios"]
    O["Bridge responde en\ndb/pull/response"]
    P["ESP32 elige operario\nPublica caja_paletizada\nestado: true, id_operario"]
    Q["Publica pallet_full → SCADA\ncurrent_pallet_count = 0, cobot_next_pallet++"]
    R["Publica caja_paletizada\nestado: false"]
    S["Bridge Rust\nupsert palet\nvincula caja\nasigna operario si cierre"]
    T["cobot_in_progress = false"]

    A --> B --> C --> D --> E --> F --> G
    G --> H
    G --> I --> J --> K --> L --> M
    M -->|Sí| N --> O --> P --> Q --> S --> T
    M -->|No| R --> S --> T
```

---

## 4. Ciclo de emergencia

```mermaid
stateDiagram-v2
    [*] --> Operativo

    Operativo --> Emergencia : estop\n(botón GPIO38 / MQTT / AMR)
    Emergencia --> Operativo : resume\n(botón GPIO39 / MQTT)

    state Operativo {
        [*] --> Normal
        Normal --> Normal : procesa comandos\nspawn, pick, AMR, Cobot
    }

    state Emergencia {
        [*] --> Detenido
        Detenido --> Detenido : ignora scada/action\nPython bridge vacía cola de picks
        note right of Detenido
            LED encendido
            Buzzer activo
            Publica status: active
        end note
    }

    Operativo --> Operativo : comandos SCADA normales
```

---

## 5. Flujo del pallet — cierre con operario

```mermaid
sequenceDiagram
    participant Cobot
    participant ESP32
    participant Bridge as Bridge Rust
    participant DB as PostgreSQL
    participant SCADA

    loop Hasta 12 cajas
        Cobot->>ESP32: completed {id_pallet: "P0001"}
        ESP32->>ESP32: current_pallet_count++
        ESP32->>Bridge: db/push · caja_paletizada {estado: false}
        Bridge->>DB: upsert palet + UPDATE caja.id_palet
    end

    Note over ESP32: pallet_counts[i] = 12 → cierre
    ESP32->>Bridge: db/pull · {query: "operarios"}
    Bridge->>DB: SELECT id_operario, nombre, apellido FROM operario
    DB-->>Bridge: filas
    Bridge-->>ESP32: db/pull/response · {operarios: [...]}
    ESP32->>ESP32: elige id_operario aleatoriamente
    ESP32->>Bridge: db/push · caja_paletizada {estado: true, id_operario: "OP003"}
    Bridge->>DB: upsert palet (estado=true)\nUPDATE palet SET id_operario="OP003"
    ESP32->>SCADA: scada/status · pallet_full {id_palet: "P0001"}
    ESP32->>ESP32: pallet_counts[i] = 0\nrota al siguiente pallet
```

---

## 6. Mapa de topics MQTT

```mermaid
flowchart LR
    subgraph ESP32_pub ["ESP32 publica"]
        direction TB
        t1["robodk/action\nspawn"]
        t2["delta/action\npick"]
        t3["amr/action\ngoto"]
        t4["cobot/action\nstart"]
        t5["scada/status\nestado / batch_complete / pallet_full"]
        t6["emergency/status\nemergency_active / emergency_inactive"]
        t7["db/push\nBOX_COMPLETED / caja_paletizada"]
        t8["db/pull\nquery: operarios"]
    end

    subgraph ESP32_sub ["ESP32 suscrito"]
        direction TB
        s1["camera/data"]
        s2["scada/action\ngen / set_mode / status / reset"]
        s3["scada/status\ndone (confirmación Delta)"]
        s4["amr/status\narrived"]
        s5["cobot/status\ncompleted"]
        s6["emergency/action\nestop / resume"]
        s7["db/pull/response"]
    end

    subgraph Bridge_Rust ["Bridge Rust suscrito"]
        direction TB
        b1["db/push"]
        b2["db/pull"]
        b3["scada/action (cmd: gen)"]
    end

    subgraph Python ["Python Bridge suscrito"]
        direction TB
        p1["robodk/action"]
        p2["delta/action"]
        p3["emergency/status"]
    end

    t7 --> b1
    t8 --> b2
    t2 --> p2
    t1 --> p1
    t6 --> p3
    s2 --> b3
```

---

## 7. Arquitectura interna del firmware ESP32 (tareas concurrentes)

```mermaid
flowchart TD
    subgraph ESP32["ESP32-S3 — Tareas concurrentes"]
        direction TB

        WM["wifi-manager\n(Core 0)\nConexión y reconexión Wi-Fi"]
        MQTT["mqtt-manager\n(callback driver)\nRecepción y despacho MQTT"]
        VT["vision-task\n(hilo)\nFiltrado de detecciones\nprecision > 0.95"]
        LT["logic-task\n(hilo)\nSpawn · Validación · AMR · Cobot\nbucle cada 500 ms"]
        ET["emergency-task\n(hilo principal)\nGPIO38 estop · GPIO39 resume\nLED · Buzzer"]

        CS[("ControlState\nArc&lt;Mutex&gt;\nEstado compartido")]

        VT -->|VisionSample\n(canal)| LT
        MQTT -->|handle_scada| LT
        MQTT -->|handle_amr| LT
        MQTT -->|handle_cobot| LT
        MQTT -->|handle_emergency| ET

        WM -->|wifi_ready: AtomicBool| MQTT
        LT <--> CS
        VT <--> CS
        ET <--> CS
        MQTT <--> CS
    end

    NVS[("NVS Flash\ntolva_counts")]
    LT -->|guarda| NVS
    LT -->|carga al arrancar| NVS
```
