from robodk import robolink
from robodk import robomath

import json
import queue
import threading
import time
import logging

import config

logging.basicConfig(
    filename=r"C:\p\c\robodk_log.txt",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("giirob")

# ---------------------------------------------------------------------------
# Escena RoboDK
# ---------------------------------------------------------------------------

RDK   = robolink.Robolink()
robot = RDK.Item(config.ROBOT_NAME, robolink.ITEM_TYPE_ROBOT)
if not robot.Valid():
    raise RuntimeError(f"Robot '{config.ROBOT_NAME}' no encontrado en la escena RoboDK")

# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------

_emergency      = False
_emergency_lock = threading.Lock()

# Cola productor-consumidor para serializar picks del Delta.
# El hilo MQTT produce órdenes; pick_worker las consume una a una.
pick_queue: queue.Queue = queue.Queue()

# Hilo consumidor — se lanza una sola vez al importar este módulo
_worker_thread: threading.Thread = None

# Lock para operaciones RoboDK que no son thread-safe (Copy/Paste)
_rdk_lock = threading.Lock()


def _is_emergency() -> bool:
    with _emergency_lock:
        return _emergency


def _set_emergency(active: bool) -> None:
    global _emergency
    with _emergency_lock:
        _emergency = active
    if active:
        # Drena la cola: descarta picks pendientes para no ejecutarlos con coordenadas obsoletas
        drained = 0
        while not pick_queue.empty():
            try:
                pick_queue.get_nowait()
                pick_queue.task_done()
                drained += 1
            except queue.Empty:
                break
        if drained:
            log.warning("Emergencia: %d pick(s) descartados de la cola", drained)


# ---------------------------------------------------------------------------
# handle_message — punto de entrada desde MqttListener
# ---------------------------------------------------------------------------

def handle_message(mqttc: object, topic: str, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("JSON inválido en [%s]: %s", topic, raw)
        return

    log.debug("Mensaje en [%s]: %s", topic, raw)

    if topic == config.TOPIC_ROBODK_ACTION:
        cmd = payload.get("cmd", "").lower()
        if cmd == "spawn":
            # Ejecutar en hilo para no bloquear el bucle MQTT
            threading.Thread(
                target=_handle_spawn, args=(payload, mqttc), daemon=True
            ).start()
        else:
            log.warning("Comando robodk desconocido: %s", cmd)

    elif topic == config.TOPIC_DELTA_ACTION:
        cmd = payload.get("cmd", "").lower()
        if cmd == "pick":
            _handle_pick(payload)
        else:
            log.warning("Comando delta desconocido: %s", cmd)

    elif topic == config.TOPIC_EMERGENCY:
        _handle_emergency(payload)


# ---------------------------------------------------------------------------
# Spawn — crea la tapa en la escena y publica detección de cámara
# ---------------------------------------------------------------------------

def _handle_spawn(payload: dict, mqttc: object) -> None:
    """
    Recibe {"cmd":"spawn","color":"blue","cap_id":"cap_42"} del ESP32.
    Clona tapa_template, la colorea, la posiciona en Frame Cinta
    y publica la detección de cámara con el mismo cap_id.
    """
    if _is_emergency():
        msg = "Spawn ignorado — emergencia activa"
        RDK.ShowMessage(msg, False); print(msg)
        return

    color  = payload.get("color", "").lower()
    cap_id = payload.get("cap_id", "")

    if color not in config.COLOR_RGB:
        msg = f"Spawn: color desconocido '{color}'"
        RDK.ShowMessage(msg, False); print(msg)
        return
    if not cap_id:
        msg = "Spawn: cap_id ausente"
        RDK.ShowMessage(msg, False); print(msg)
        return

    template = RDK.Item(config.CAP_TEMPLATE, robolink.ITEM_TYPE_OBJECT)
    if not template.Valid():
        msg = f"Plantilla '{config.CAP_TEMPLATE}' no encontrada"
        RDK.ShowMessage(msg, False); print(msg)
        return

    # Clonar la plantilla (Copy/Paste no es thread-safe)
    with _rdk_lock:
        RDK.Copy(template)
        cap = RDK.Paste()

    cap.setName(cap_id)
    cap.Recolor(config.COLOR_RGB[color])

    # Posicionar en Frame Cinta; si no existe usa la posición del template
    frame = RDK.Item(config.SPAWN_FRAME, robolink.ITEM_TYPE_FRAME)
    if frame.Valid():
        cap.setPoseAbs(frame.PoseAbs())
    else:
        cap.setPoseAbs(template.PoseAbs())

    time.sleep(config.SPAWN_DELAY_S)

    # Leer posición absoluta y publicar como detección de cámara
    pose = cap.PoseAbs()
    x = round(pose[0, 3], 2)
    y = round(pose[1, 3], 2)

    camera_msg = json.dumps({
        "x":         x,
        "y":         y,
        "color":     color,
        "precision": config.PICK_PRECISION,
        "cap_id":    cap_id,
    })

    mqttc.publish(config.TOPIC_CAMERA_DATA, camera_msg, qos=config.MQTT_QOS)
    RDK.ShowMessage(f"Spawn: {cap_id} {color} → cámara publicada ({x}, {y})")
    log.info("Spawn completado: %s color=%s pos=(%.1f, %.1f)", cap_id, color, x, y)


# ---------------------------------------------------------------------------
# Pick — encola la orden para el hilo consumidor
# ---------------------------------------------------------------------------

def _handle_pick(payload: dict) -> None:
    if _is_emergency():
        RDK.ShowMessage("Pick ignorado — emergencia activa")
        return

    if not all(k in payload for k in ("x", "y", "tolva", "cap_id")):
        RDK.ShowMessage("Pick: payload incompleto")
        return

    pick_queue.put(payload)
    RDK.ShowMessage(f"Pick encolado: {payload['cap_id']} → {payload['tolva']}")
    log.info("Pick encolado: cap_id=%s tolva=%s (cola: %d)",
             payload["cap_id"], payload["tolva"], pick_queue.qsize())


# ---------------------------------------------------------------------------
# Emergencia
# ---------------------------------------------------------------------------

def _handle_emergency(payload: dict) -> None:
    status = payload.get("status", "").lower()
    if status == "active":
        _set_emergency(True)
        RDK.ShowMessage("EMERGENCIA ACTIVA — sistema detenido")
        log.warning("EMERGENCIA ACTIVA — sistema detenido")
    elif status == "operative":
        _set_emergency(False)
        RDK.ShowMessage("Emergencia resuelta — sistema operativo")
        log.info("Emergencia resuelta — sistema operativo")


# ---------------------------------------------------------------------------
# Hilo consumidor de picks (patrón productor-consumidor)
# ---------------------------------------------------------------------------

def _pick_worker() -> None:
    log.info("pick_worker iniciado")
    while True:
        order = pick_queue.get()
        if order is None:  # sentinel de parada
            break

        while _is_emergency():
            log.info("pick_worker: esperando fin de emergencia...")
            time.sleep(0.5)

        cap_id = order["cap_id"]
        tolva  = order["tolva"].lower()
        x      = float(order["x"])
        y      = float(order["y"])

        log.info("Ejecutando pick: cap_id=%s tolva=%s x=%.1f y=%.1f", cap_id, tolva, x, y)
        try:
            _execute_pick(cap_id, tolva, x, y)
        except Exception as exc:
            log.error("Error en pick %s: %s", cap_id, exc)
        finally:
            pick_queue.task_done()


def _execute_pick(cap_id: str, tolva: str, x: float, y: float) -> None:
    """
    Mueve el Delta para recoger la tapa y depositarla en la tolva.
    TODO: implementar secuencia MoveJ/MoveL: approach → pick → approach → tolva → home.
    """
    RDK.ShowMessage(f"Pick ejecutado: {cap_id} → {tolva}")
    log.info("Pick recibido: cap_id=%s tolva=%s x=%.1f y=%.1f (sin implementar)", cap_id, tolva, x, y)


# ---------------------------------------------------------------------------
# Arranque del hilo consumidor al importar el módulo
# ---------------------------------------------------------------------------

_worker_thread = threading.Thread(target=_pick_worker, name="pick-worker", daemon=True)
_worker_thread.start()
