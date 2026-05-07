# Configuracion RoboDK — Demo Integracion
# Ajustar los nombres para que coincidan con la escena abierta en RoboDK

# ---------------------------------------------------------------------------
# Escenario 2 — Delta / camara
# ---------------------------------------------------------------------------
ROBOT_NAME    = "ABB IRB 360-1/1600 4D"
CAP_TEMPLATE  = "tapa_template"
SPAWN_FRAME   = "Frame Cinta"

SPAWN_DELAY_S  = 0.5
PICK_PRECISION = 0.99

# ---------------------------------------------------------------------------
# Escenario 1 — Cobot
# ---------------------------------------------------------------------------
EXTERNAL_AXIS_NAME = "Gudel TMF-2"
COBOT_NAME         = "ABB CRB 15000 10"
TOOL_NAME          = "Pinza"

ZONE_1_NAME    = "zona_paletizado_1"
ZONE_2_NAME    = "zona_paletizado_2"
ZONE_3_NAME    = "zona_paletizado_3"

COBOT_BASE_NAME    = "ABB CRB 15000 10 Base"
PLACE_FRAME_NAME   = "frame_place_cobot"
PICK_FRAME_NAME    = "frame_pick_cobot"

PRE_PLACE_NAME  = "pre_place_cobot"
PLACE_NAME      = "place_cobot"
POST_PLACE_NAME = "post_place_cobot"
PRE_PICK_NAME   = "pre_pick_cobot"
PICK_NAME       = "pick_cobot"
POST_PICK_NAME  = "post_pick_cobot"
HOME_COBOT_NAME = "home_cobot"

# Geometría de apilado
BOX_OFFSET = 520.0
BOX_WIDTH  = 440.0
BOX_HEIGHT = 440.0

# Debe coincidir con PALLET_CAPACITY del ESP32
PALLET_CAPACITY = 2

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
BROKER    = "broker.hivemq.com"
PORT      = 1883
CLIENT_ID = "robodk-demo-integracion"

BASE = "giirob/pr2-A1"
TOPIC_ROBODK_ACTION = BASE + "/devices/robodk/action"
TOPIC_CAMERA_DATA   = BASE + "/devices/camera/data"
TOPIC_COBOT_ACTION  = BASE + "/devices/cobot/action"
TOPIC_COBOT_STATUS  = BASE + "/devices/cobot/status"
MQTT_QOS            = 1

# ---------------------------------------------------------------------------
# Mapa color -> RGB para Recolor()
# ---------------------------------------------------------------------------
COLOR_RGB = {
    "red":    (1.0, 0.0, 0.0),
    "green":  (0.0, 1.0, 0.0),
    "blue":   (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "orange": (1.0, 0.5, 0.0),
    "white":  (1.0, 1.0, 1.0),
}
