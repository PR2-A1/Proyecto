# Configuracion RoboDK — Demo Escenario 2
# Ajustar los nombres para que coincidan con la escena abierta en RoboDK

ROBOT_NAME    = "ABB IRB 360-1/1600 4D"
CAP_TEMPLATE  = "tapa_template"
SPAWN_FRAME   = "Frame Cinta"

# Delay (s) entre clonar la tapa y leer su posición
SPAWN_DELAY_S = 0.5

# Precision reportada en camera/data
PICK_PRECISION = 0.99

# MQTT
BROKER    = "broker.hivemq.com"
PORT      = 1883
CLIENT_ID = "robodk-demo-escenario2"

BASE = "giirob/pr2-A1"
TOPIC_ROBODK_ACTION = BASE + "/devices/robodk/action"
TOPIC_CAMERA_DATA   = BASE + "/devices/camera/data"
MQTT_QOS            = 1

# Mapa color → RGB para Recolor()
COLOR_RGB = {
    "red":    (1.0, 0.0, 0.0),
    "green":  (0.0, 1.0, 0.0),
    "blue":   (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "orange": (1.0, 0.5, 0.0),
    "white":  (1.0, 1.0, 1.0),
}
