# SCADA GIIROB — Cliente PyQt5

Cliente SCADA del proyecto **GIIROB PR2-A1**. Conecta al broker MQTT público,
observa el estado del ESP32-S3 y permite operar la célula desde una HMI.

Basado en [SCADA_diseño.md](../SCADA_diseño.md) y compatible con las claves de
[mqtt_messages.md](../mqtt_messages.md).

---

## Requisitos

- Python ≥ 3.9
- PyQt5
- paho-mqtt 1.x

Instalación recomendada con entorno virtual:

```bash
cd c/scada
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

```bash
python main.py
```

Al arrancar:
1. El SCADA se conecta a `broker.hivemq.com:1883`.
2. Se suscribe a los topics relevantes del proyecto.
3. Solicita un `status` inmediato para sincronizar la HMI.
4. Refresca el estado cada 10 segundos.

## Estructura del proyecto

| Archivo | Responsabilidad |
|---|---|
| `main.py` | Entry point — instancia `QApplication` y la ventana principal. |
| `main_window.py` | Ensamblaje de paneles, cableado de señales MQTT y handlers de botones. |
| `widgets.py` | Paneles reutilizables: cabecera, tolvas, pallets, AMR, cobot, cámara, log. |
| `dialogs.py` | Diálogos modales: nuevo lote, tapa manual, confirmar entrega. |
| `mqtt_client.py` | Cliente paho-mqtt aislado en su hilo, expone señales Qt. |
| `state.py` | `SystemState` — réplica del `ControlState` del firmware. |
| `config.py` | Broker, topics, colores de tolva, umbrales, paleta visual. |

## Topics

**Publicados por el SCADA:**
- `giirob/pr2-A1/devices/scada/action` — `gen`, `set_mode`, `status`, `reset`.
- `giirob/pr2-A1/devices/scada/status` — `done` (confirmación de entrega, debug).
- `giirob/pr2-A1/system/emergency/action` — `estop`, `resume`.

**Suscritos por el SCADA:**
- `giirob/pr2-A1/devices/scada/status` — bloque de estado, `batch_complete`, `pallet_full`.
- `giirob/pr2-A1/devices/amr/status` — estado del AMR.
- `giirob/pr2-A1/devices/cobot/status` — confirmación de paletizado.
- `giirob/pr2-A1/system/emergency/status` — emergencia activa/inactiva.
- `giirob/pr2-A1/devices/camera/data` — detecciones de cámara (informativo).
- `giirob/pr2-A1/db/push` — eventos de caja para diagnóstico.

## Controles

| Botón | Mensaje publicado |
|---|---|
| Nuevo lote (Auto) | `set_mode auto` + `gen` con `id_lote`, `quantity`, opcional `proveedor` |
| Tapa manual | `set_mode manual` + `gen` con `id_lote`, `color`, `quantity:1` |
| Modo Auto / Manual | `set_mode` |
| Solicitar estado | `status` |
| Confirmar tapa (debug) | `done` con `id_cap` y `tolva` |
| Reset | `reset` (confirmación modal) |
| EMERGENCIA | `estop` con `source:"SCADA"` |
| Reanudar | `resume` con `source:"SCADA"` |

## Notas

- El SCADA **nunca** publica directamente en `delta/action`, `amr/action`,
  `cobot/action` ni `robodk/action`. Todas las órdenes a dispositivos viajan
  por el ESP32, que mantiene los invariantes del sistema.
- Si el broker desconecta, paho-mqtt reintenta automáticamente con backoff
  1–30 s. El indicador "MQTT: desconectado" pasa a rojo durante el corte.
- El timer de refresco emite un `status` cada 10 s para mantener la HMI
  sincronizada aunque se pierda un mensaje suelto.
