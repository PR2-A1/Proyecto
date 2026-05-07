"""
Escenario 1 — Control del cobot ABB CRB 15000.
Recibe {"cmd":"start","id_pallet":N,"caja_id":"C000X","color":"RED",
        "mode":"pallet","location":"PALLET_1"}
Ejecuta ciclo pick -> paletizar -> publica FINISHED en cobot/status.
"""

from robodk import robolink, robomath
import json
import math
import threading
import logging
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

log = logging.getLogger("demo_esc1")

RDK = robolink.Robolink()

# ---------------------------------------------------------------------------
# Items de RoboDK
# ---------------------------------------------------------------------------
external_axis = RDK.Item(config.EXTERNAL_AXIS_NAME, robolink.ITEM_TYPE_ROBOT)
cobot         = RDK.Item(config.COBOT_NAME,         robolink.ITEM_TYPE_ROBOT)
tool          = RDK.Item(config.TOOL_NAME,           robolink.ITEM_TYPE_TOOL)

zone_targets = {
    "PALLET_1": RDK.Item(config.ZONE_1_NAME, robolink.ITEM_TYPE_TARGET),
    "PALLET_2": RDK.Item(config.ZONE_2_NAME, robolink.ITEM_TYPE_TARGET),
    "PALLET_3": RDK.Item(config.ZONE_3_NAME, robolink.ITEM_TYPE_TARGET),
}

pre_place_target  = RDK.Item(config.PRE_PLACE_NAME,  robolink.ITEM_TYPE_TARGET)
place_target      = RDK.Item(config.PLACE_NAME,       robolink.ITEM_TYPE_TARGET)
post_place_target = RDK.Item(config.POST_PLACE_NAME,  robolink.ITEM_TYPE_TARGET)
pre_pick_target   = RDK.Item(config.PRE_PICK_NAME,    robolink.ITEM_TYPE_TARGET)
pick_target       = RDK.Item(config.PICK_NAME,         robolink.ITEM_TYPE_TARGET)
post_pick_target  = RDK.Item(config.POST_PICK_NAME,   robolink.ITEM_TYPE_TARGET)
home_cobot        = RDK.Item(config.HOME_COBOT_NAME,  robolink.ITEM_TYPE_TARGET)

cobot_base  = RDK.Item(config.COBOT_BASE_NAME,  robolink.ITEM_TYPE_FRAME)
place_frame = RDK.Item(config.PLACE_FRAME_NAME, robolink.ITEM_TYPE_FRAME)
pick_frame  = RDK.Item(config.PICK_FRAME_NAME,  robolink.ITEM_TYPE_FRAME)

_cobot_lock    = threading.Lock()
_box_iteration = 0


# ---------------------------------------------------------------------------
# Punto de entrada desde RobotController
# ---------------------------------------------------------------------------

def handle_cobot_action(mqttc, payload: dict) -> None:
    cmd = payload.get("cmd", "").lower()
    if cmd == "start":
        threading.Thread(
            target=_palletizing_cycle,
            args=(payload, mqttc),
            daemon=True,
        ).start()
    else:
        log.warning("Comando cobot desconocido: %s", cmd)


# ---------------------------------------------------------------------------
# Ciclo completo de paletizado
# ---------------------------------------------------------------------------

def _palletizing_cycle(payload: dict, mqttc) -> None:
    global _box_iteration

    pallet_id = payload.get("id_pallet", 0)
    color     = payload.get("color", "").lower()
    location  = payload.get("location", "PALLET_1")

    zone = zone_targets.get(location)
    if zone is None or not zone.Valid():
        log.error("Zona '%s' no encontrada en RoboDK", location)
        return

    with _cobot_lock:
        iteration      = _box_iteration
        _box_iteration += 1
        if _box_iteration >= config.PALLET_CAPACITY:
            _box_iteration = 0

    log.info("Ciclo paletizado — pallet=%d color=%s zona=%s iter=%d",
             pallet_id, color, location, iteration)

    try:
        _pick()
        _place(zone, color, iteration)
        _publish_finished(mqttc, pallet_id)
    except Exception as e:
        log.error("Error en ciclo de paletizado: %s", e)


# ---------------------------------------------------------------------------
# Pick
# ---------------------------------------------------------------------------

def _pick() -> None:
    cobot.setPoseFrame(pick_frame)
    cobot.MoveJ(pre_pick_target)
    cobot.MoveL(pick_target)
    tool.AttachClosest()
    cobot.MoveL(post_pick_target)


# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------

def _place(zone, color: str, box_iteration: int) -> None:
    external_axis.MoveL(zone)

    if color in ('red', 'green', 'blue'):
        place_frame.setPose(place_frame.Pose() * robomath.rotz(-90 * math.pi / 180))
        direction = -1
    else:
        place_frame.setPose(place_frame.Pose() * robomath.rotz(90 * math.pi / 180))
        direction = 1

    x = 170.0
    y = direction * (config.BOX_OFFSET + config.BOX_WIDTH * (box_iteration % 2))
    z = config.BOX_HEIGHT * (box_iteration // 2)
    place_frame.setPos([x, y, z])

    cobot.setPoseFrame(place_frame)
    cobot.MoveJ(pre_place_target)
    cobot.MoveJ(place_target)
    tool.DetachClosest()
    cobot.MoveL(post_place_target)

    cobot.setPoseFrame(cobot_base)
    cobot.MoveJ(home_cobot)


# ---------------------------------------------------------------------------
# Publicar FINISHED
# ---------------------------------------------------------------------------

def _publish_finished(mqttc, pallet_id: int) -> None:
    msg = json.dumps({"status": "COMPLETED", "id_pallet": pallet_id})
    mqttc.publish(config.TOPIC_COBOT_STATUS, msg, qos=config.MQTT_QOS)
    log.info("FINISHED publicado — pallet_id=%d", pallet_id)
