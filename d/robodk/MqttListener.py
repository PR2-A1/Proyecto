import paho.mqtt.client as mqtt
import RobotController as rc
from robodk import robolink
from robolink import *

RDK = robolink.Robolink()

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

TOPIC_ROBODK_ACTION    = BASE + "/devices/robodk/action"
TOPIC_DELTA_ACTION     = BASE + "/devices/delta/action"
TOPIC_CAMERA_DATA      = BASE + "/devices/camera/data"
TOPIC_SCADA_ACTION     = BASE + "/devices/scada/action"
TOPIC_SCADA_STATUS     = BASE + "/devices/scada/status"
TOPIC_AMR_ACTION       = BASE + "/devices/amr/action"
TOPIC_AMR_STATUS       = BASE + "/devices/amr/status"
TOPIC_COBOT_ACTION     = BASE + "/devices/cobot/action"
TOPIC_COBOT_STATUS     = BASE + "/devices/cobot/status"
TOPIC_EMERGENCY_ACTION = BASE + "/system/emergency/action"
TOPIC_EMERGENCY_STATUS = BASE + "/system/emergency/status"

# ---------------------------------------------------------------------------
# Limpiar tapas de sesiones anteriores
# ---------------------------------------------------------------------------
to_delete = [item for item in RDK.ItemList(ITEM_TYPE_OBJECT)
             if item.Valid() and item.Name().startswith("C0")]
for item in to_delete:
    item.Delete()

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def on_connect(mqttc, obj, flags, rc_code):
    if rc_code == 0:
        print("[MQTT] Conectado al broker")
        mqttc.subscribe(TOPIC_ROBODK_ACTION,    qos=1)
        mqttc.subscribe(TOPIC_COBOT_ACTION,     qos=1)
        mqttc.subscribe(TOPIC_DELTA_ACTION,     qos=1)
        mqttc.subscribe(TOPIC_EMERGENCY_STATUS, qos=1)
        print(f"[MQTT] Suscrito a:\n"
              f"  {TOPIC_ROBODK_ACTION}\n"
              f"  {TOPIC_COBOT_ACTION}\n"
              f"  {TOPIC_DELTA_ACTION}\n"
              f"  {TOPIC_EMERGENCY_STATUS}")
        RDK.ShowMessage("MQTT conectado", False)
    else:
        print(f"[MQTT] Error de conexion: rc={rc_code}")
        RDK.ShowMessage(f"MQTT error: {rc_code}", False)

def on_message(mqttc, obj, msg):
    payload = msg.payload.decode("utf-8")
    topic   = msg.topic
    print(f"[MQTT] [{topic}]: {payload}")
    RDK.ShowMessage(f"[{topic.split('/')[-1]}] {payload}", False)
    rc.handle_message(mqttc, topic, payload)

def on_disconnect(mqttc, obj, rc_code):
    print(f"[MQTT] Desconectado: rc={rc_code}")
    RDK.ShowMessage("MQTT desconectado", False)

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

mqttc = mqtt.Client(client_id="robodk-giirob")
mqttc.on_connect    = on_connect
mqttc.on_message    = on_message
mqttc.on_disconnect = on_disconnect

if USER:
    mqttc.username_pw_set(username=USER, password=PASSWD)

mqttc.connect(BROKER, PORT, keepalive=60)
mqttc.loop_forever()
