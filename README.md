# GiiRob PR2-A1 — Proyecto

Repositorio del sistema de clasificación automatizada de tapas plásticas del grupo PR2-A1.

## Estructura

```
c/    Firmware final ESP32-S3 (Rust)
d/    Prototipo demo
```

## Carpeta `c` — Firmware final

Contiene el firmware en Rust para ESP32-S3. Es la versión definitiva del controlador central del sistema: gestiona la comunicación MQTT con el SCADA y coordina el robot Delta, el AMR y el Cobot.

Ver [`c/README.md`](c/README.md) para detalles de compilación y documentación.

## Carpeta `d` — Prototipo demo

Versión de demostración utilizada durante el desarrollo previo. Sirvió como banco de pruebas del sistema completo (ESP32, bridge, RoboDK, base de datos) pero **no representa la versión final** — a lo largo del desarrollo cambiaron la arquitectura del firmware, los topics MQTT, la lógica de coordinación de robots y el esquema de base de datos. Se mantiene en el repositorio como referencia del proceso de iteración.
