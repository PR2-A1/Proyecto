# GiiRob PR2-A1 — Firmware ESP32-S3

Firmware en Rust para ESP32-S3 que controla una línea de producción automatizada de tapas plásticas. El sistema coordina tres robots vía MQTT: un **Delta** (clasificador), un **AMR** (transporte) y un **Cobot** (paletizado), recibiendo órdenes del SCADA y publicando eventos al broker.

## Estructura

```
src/                 Código fuente Rust (firmware ESP32-S3)
  main.rs            Arranque, inicialización y recursos compartidos
  config.rs          Constantes del sistema (Wi-Fi, MQTT, umbrales)
  logic_task.rs      Lógica principal: spawns, AMR, Cobot, publicaciones MQTT
  emergency_task.rs  Botones, LED, buzzer y parada de emergencia
  mqtt_manager.rs    Callback MQTT y despacho de eventos
  wifi_manager.rs    Conexión y reconexión Wi-Fi
  control_state.rs   Estado compartido del sistema

documentacion/       Documentación del proyecto
```

## Documentación

| Archivo | Contenido |
|---|---|
| `documentacion/SISTEMA.md` | Arquitectura, tareas, flujos y configuración del firmware |
| `documentacion/mqtt_messages.md` | Referencia completa de topics y payloads MQTT |
| `documentacion/Pruebas_sistema.md` | Guía de pruebas de integración end-to-end |
| `documentacion/SETUP_RUST_ESP.md` | Cómo compilar y flashear el firmware |

## Compilar y flashear

```bash
cargo build
cargo run   # flashea y abre monitor serie
```

Requiere tener instalado el toolchain de Rust para Xtensa. Ver `documentacion/SETUP_RUST_ESP.md`.
