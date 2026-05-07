# Broker MQTT
MQTT_HOST      = "broker.hivemq.com"
MQTT_PORT      = 1883
MQTT_CLIENT_ID = "robodk-giirob"
MQTT_QOS       = 1

# Topics suscritos
TOPIC_ROBODK_ACTION = "giirob/pr2-A1/devices/robodk/action"
TOPIC_DELTA_ACTION  = "giirob/pr2-A1/devices/delta/action"
TOPIC_EMERGENCY     = "giirob/pr2-A1/system/emergency/status"

# Topics publicados
TOPIC_CAMERA_DATA = "giirob/pr2-A1/devices/camera/data"

# ---------------------------------------------------------------------------
# Nombres de ítems en la escena RoboDK
# ---------------------------------------------------------------------------

# Robot Delta (clasificador de tapas)
ROBOT_NAME = "ABB IRB 360-1/1600 4D"

# Objeto plantilla que se clona para crear cada tapa nueva
CAP_TEMPLATE = "tapa_template"

# Posición de spawn de la tapa en la cinta.
# Es un Frame (no un Target); si no existe se usa la posición del propio template.
SPAWN_FRAME = "Frame Cinta"

# Targets de aproximación y home para el Delta.
# Deben crearse en la escena RoboDK; si no existen, los movimientos opcionales se omiten.
TARGET_HOME          = "home_delta"
TARGET_PICK_APPROACH = "approach_delta"

# Target de cada tolva — nombres tal como aparecen en el árbol de RoboDK
TOLVA_TARGETS = {
    "tolva_1": "target_tolva_rojo",
    "tolva_2": "target_tolva_amarillo",
    "tolva_3": "target_tolva_verde",
    "tolva_4": "target_tolva_blanco",
    "tolva_5": "target_tolva_naranja",
    "tolva_6": "target_tolva_azul",
}

# ---------------------------------------------------------------------------
# Parámetros de simulación
# ---------------------------------------------------------------------------

# Colores RGB normalizados [0..1] para colorear el objeto de la tapa
COLOR_RGB = {
    "red":    [1.0, 0.0, 0.0, 1.0],
    "yellow": [1.0, 1.0, 0.0, 1.0],
    "green":  [0.0, 0.8, 0.0, 1.0],
    "white":  [1.0, 1.0, 1.0, 1.0],
    "orange": [1.0, 0.5, 0.0, 1.0],
    "blue":   [0.0, 0.4, 1.0, 1.0],
}

SPAWN_DELAY_S  = 0.5   # segundos entre crear la tapa y publicar la detección de cámara
PICK_PRECISION = 0.99  # precisión fija que publica la cámara simulada
PICK_Z         = 0.0   # altura Z del punto de pick en coordenadas mundo (ajustar según escena)
