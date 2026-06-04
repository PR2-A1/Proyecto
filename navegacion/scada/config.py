"""Configuración estática del SCADA.

Centraliza broker, topics, mapeo tolva-color, umbrales y paleta visual.
Cambios de aquí afectan a todo el SCADA, el resto de módulos no han de ser tocados.
"""

from __future__ import annotations


# Broker MQTT
MQTT_HOST = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 30
MQTT_CLIENT_ID_PREFIX = "scada-giirob-"


# Topics
TOPIC_SCADA_ACTION = "giirob/pr2-A1/devices/scada/action"
TOPIC_SCADA_STATUS = "giirob/pr2-A1/devices/scada/status"
TOPIC_CAMERA_DATA = "giirob/pr2-A1/devices/camera/data"
TOPIC_DELTA_ACTION = "giirob/pr2-A1/devices/delta/action"
TOPIC_AMR_ACTION = "giirob/pr2-A1/devices/amr/action"
TOPIC_AMR_STATUS = "giirob/pr2-A1/devices/amr/status"
TOPIC_COBOT_ACTION = "giirob/pr2-A1/devices/cobot/action"
TOPIC_COBOT_STATUS = "giirob/pr2-A1/devices/cobot/status"
TOPIC_ROBODK_ACTION = "giirob/pr2-A1/devices/robodk/action"
TOPIC_EMERGENCY_ACTION = "giirob/pr2-A1/system/emergency/action"
TOPIC_EMERGENCY_STATUS = "giirob/pr2-A1/system/emergency/status"
TOPIC_DB_PUSH = "giirob/pr2-A1/db/push"
TOPIC_DB_PULL = "giirob/pr2-A1/db/pull"
TOPIC_DB_PULL_RESPONSE = "giirob/pr2-A1/db/pull/response"

# Topics for SCADA to suscribe
SUBSCRIBE_TOPICS = [
    TOPIC_SCADA_STATUS,
    TOPIC_AMR_ACTION,
    TOPIC_AMR_STATUS,
    TOPIC_COBOT_ACTION,
    TOPIC_COBOT_STATUS,
    TOPIC_EMERGENCY_STATUS,
    TOPIC_CAMERA_DATA,
    TOPIC_DELTA_ACTION,
    TOPIC_ROBODK_ACTION,
    TOPIC_DB_PUSH,
    TOPIC_DB_PULL_RESPONSE,
]


# Maping for "TOLVA"
VALID_COLORS = ["red", "yellow", "green", "white", "orange", "blue"]

TOLVA_COLOR = {
    "TOLVA_1": "red",
    "TOLVA_2": "yellow",
    "TOLVA_3": "green",
    "TOLVA_4": "white",
    "TOLVA_5": "orange",
    "TOLVA_6": "blue",
}

# Hex for each color.
COLOR_HEX = {
    "red": "#e74c3c",
    "yellow": "#f1c40f",
    "green": "#2ecc71",
    "white": "#ecf0f1",
    "orange": "#e67e22",
    "blue": "#3498db",
}


# Limits
AMR_TOLVA_THRESHOLD = 20
AMR_ARRIVAL_DELAY_SECS = 6
PALLET_CAPACITY = 6   
PALLET_COUNT = 6


# Palette and style
class Palette:
    """Paleta de colores del SCADA. Inicializa los atributos en el constructor
    para mantener el mismo patrón que el resto de clases del proyecto."""

    def __init__(self) -> None:
        self.bg: str = "#1e1e2e"
        self.surface: str = "#2a2a3e"
        self.surface_alt: str = "#34344a"
        self.border: str = "#44475a"
        self.text: str = "#f8f8f2"
        self.text_dim: str = "#6272a4"
        self.accent: str = "#8be9fd"
        self.ok: str = "#2ecc71"
        self.warn: str = "#f1c40f"
        self.error: str = "#e74c3c"
        self.auto: str = "#bd93f9"
        self.manual: str = "#ffb86c"


PALETTE = Palette()


STATUS_REQUEST_INTERVAL_MS = 10_000
LOG_MAX_LINES = 500
