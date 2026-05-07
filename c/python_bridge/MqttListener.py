import paho.mqtt.client as mqtt
import RobotController as rc

# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------
BROKER = "broker.hivemq.com"
PORT   = 1883
USER   = ""
PASSWD = ""

# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
BASE = "giirob/pr2-A1"

# RoboDK
TOPIC_ROBODK_ACTION  = BASE + "/devices/robodk/action"

# Delta
TOPIC_DELTA_ACTION   = BASE + "/devices/delta/action"

# Cámara (solo publicación desde RobotController)
TOPIC_CAMERA_DATA    = BASE + "/devices/camera/data"

# SCADA
TOPIC_SCADA_ACTION   = BASE + "/devices/scada/action"
TOPIC_SCADA_STATUS   = BASE + "/devices/scada/status"

# AMR
TOPIC_AMR_ACTION     = BASE + "/devices/amr/action"
TOPIC_AMR_STATUS     = BASE + "/devices/amr/status"

# Cobot
TOPIC_COBOT_ACTION   = BASE + "/devices/cobot/action"
TOPIC_COBOT_STATUS   = BASE + "/devices/cobot/status"

# Emergencia
TOPIC_EMERGENCY_ACTION = BASE + "/system/emergency/action"
TOPIC_EMERGENCY_STATUS = BASE + "/system/emergency/status"

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def on_connect(mqttc, obj, flags, rc):
    if rc == 0:
        print("[MQTT] Conectado al broker")
        mqttc.subscribe(TOPIC_ROBODK_ACTION,    1)
        mqttc.subscribe(TOPIC_DELTA_ACTION,     1)
        mqttc.subscribe(TOPIC_EMERGENCY_STATUS, 1)
        print("[MQTT] Suscrito a robodk/action, delta/action, emergency/status")
    else:
        print(f"[MQTT] Error de conexión: rc={rc}")

def on_message(mqttc, obj, msg):
    payload = msg.payload.decode("utf-8")
    topic   = msg.topic
    rc.handle_message(mqttc, topic, payload)

def on_disconnect(mqttc, obj, rc):
    print(f"[MQTT] Desconectado: rc={rc}")

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

mqttc = mqtt.Client(client_id="robodk-estacion")
mqttc.on_connect    = on_connect
mqttc.on_message    = on_message
mqttc.on_disconnect = on_disconnect

if USER:
    mqttc.username_pw_set(username=USER, password=PASSWD)

mqttc.connect(BROKER, PORT, keepalive=60)
mqttc.loop_forever()
