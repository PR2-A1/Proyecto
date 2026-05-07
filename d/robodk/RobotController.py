"""
Escenario 2 — RoboDK
Recibe {"cmd":"spawn","color":"red","cap_id":"C0001","lote_id":"L0001"}
desde el ESP32, clona tapa_template en la escena RoboDK y publica la
deteccion de camara en camera/data.
"""

from robodk import robolink
import json
import threading
import time
import logging
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import CobotController as cc

logging.basicConfig(
    filename=r"C:\p\demo\robodk\robodk_demo.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("demo_esc2")

# ---------------------------------------------------------------------------
# Conexion con RoboDK
# ---------------------------------------------------------------------------
RDK   = robolink.Robolink()
robot = RDK.Item(config.ROBOT_NAME, robolink.ITEM_TYPE_ROBOT)
if not robot.Valid():
    raise RuntimeError(f"Robot '{config.ROBOT_NAME}' no encontrado en RoboDK")

_rdk_lock = threading.Lock()   # Copy/Paste no es thread-safe en RoboDK


# ---------------------------------------------------------------------------
# Punto de entrada desde MqttListener
# ---------------------------------------------------------------------------

def handle_message(mqttc: object, topic: str, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("JSON invalido en [%s]: %s", topic, raw)
        return

    if topic == config.TOPIC_ROBODK_ACTION:
        cmd = payload.get("cmd", "").lower()
        if cmd == "spawn":
            threading.Thread(
                target=_spawn_tapa,
                args=(payload, mqttc),
                daemon=True,
            ).start()
        else:
            log.warning("Comando desconocido en robodk/action: %s", cmd)

    elif topic == config.TOPIC_COBOT_ACTION:
        cc.handle_cobot_action(mqttc, payload)

    else:
        log.debug("Topic no gestionado: %s", topic)


# ---------------------------------------------------------------------------
# Spawn de tapa en la escena RoboDK
# ---------------------------------------------------------------------------

def _spawn_tapa(payload: dict, mqttc: object) -> None:
    """
    1. Clona tapa_template en la escena.
    2. La colorea segun el campo 'color'.
    3. La posiciona en Frame Cinta.
    4. Publica la deteccion de camara en camera/data con (x, y, color, cap_id).
    """
    color  = payload.get("color", "").lower()
    cap_id = payload.get("cap_id", "")
    lote_id = payload.get("lote_id", "")

    if color not in config.COLOR_RGB:
        msg = f"Spawn: color desconocido '{color}'"
        RDK.ShowMessage(msg, False)
        log.warning(msg)
        return

    if not cap_id:
        msg = "Spawn: cap_id ausente en payload"
        RDK.ShowMessage(msg, False)
        log.warning(msg)
        return

    template = RDK.Item(config.CAP_TEMPLATE, robolink.ITEM_TYPE_OBJECT)
    if not template.Valid():
        msg = f"Plantilla '{config.CAP_TEMPLATE}' no encontrada"
        RDK.ShowMessage(msg, False)
        log.error(msg)
        return

    # Clonar (operacion no thread-safe en RoboDK)
    with _rdk_lock:
        RDK.Copy(template)
        cap = RDK.Paste()

    cap.setName(cap_id)
    cap.Recolor(config.COLOR_RGB[color])

    # Posicionar en Frame Cinta si existe, si no usar posicion del template
    frame = RDK.Item(config.SPAWN_FRAME, robolink.ITEM_TYPE_FRAME)
    if frame.Valid():
        cap.setPoseAbs(frame.PoseAbs())
    else:
        cap.setPoseAbs(template.PoseAbs())

    time.sleep(config.SPAWN_DELAY_S)

    # Leer posicion en escena y publicar como deteccion de camara
    pose = cap.PoseAbs()
    x = round(pose[0, 3], 2)
    y = round(pose[1, 3], 2)

    camera_msg = json.dumps({
        "x":         x,
        "y":         y,
        "color":     color,
        "precision": config.PICK_PRECISION,
        "cap_id":    cap_id,
        "lote_id":   lote_id,
    })

    mqttc.publish(config.TOPIC_CAMERA_DATA, camera_msg, qos=config.MQTT_QOS)
    RDK.ShowMessage(f"Spawn OK: {cap_id} ({color}) @ ({x:.1f},{y:.1f})", False)
    log.info("Spawn completado: cap_id=%s color=%s lote=%s pos=(%.1f,%.1f)",
             cap_id, color, lote_id, x, y)
