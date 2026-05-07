"""
Demo Escenario 2 — listener MQTT para RoboDK.
Se suscribe a robodk/action y delega los mensajes a RobotController.
Compatible con paho-mqtt < 2.0 (API sin CallbackAPIVersion).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt
import RobotController as rc
import config

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def on_connect(mqttc, obj, flags, rc_code):
    if rc_code == 0:
        mqttc.subscribe(config.TOPIC_ROBODK_ACTION, config.MQTT_QOS)
        print(f"[MQTT] Conectado y suscrito a {config.TOPIC_ROBODK_ACTION}")
    else:
        print(f"[MQTT] Error de conexion: rc={rc_code}")

def on_message(mqttc, obj, msg):
    payload = msg.payload.decode("utf-8")
    rc.handle_message(mqttc, msg.topic, payload)

def on_disconnect(mqttc, obj, rc_code):
    print(f"[MQTT] Desconectado: rc={rc_code}")

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

mqttc = mqtt.Client(client_id=config.CLIENT_ID)
mqttc.on_connect    = on_connect
mqttc.on_message    = on_message
mqttc.on_disconnect = on_disconnect

mqttc.connect(config.BROKER, config.PORT, keepalive=60)
print(f"[MQTT] Conectando a {config.BROKER}:{config.PORT}...")
mqttc.loop_forever()
