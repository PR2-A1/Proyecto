from robodk import robolink
RDK = robolink.Robolink()
import paho.mqtt.client as mqtt
import mqtt_controller as rc
import config
from robolink import ITEM_TYPE_OBJECT





def on_connect(mqttc, obj, flags, rc_code):
    if rc_code == 0:
        RDK.ShowMessage("[MQTT] Conectado al broker", False)
        mqttc.subscribe(config.TOPIC_ROBODK_ACTION, qos=config.MQTT_QOS)
        mqttc.subscribe(config.TOPIC_COBOT_ACTION,  qos=config.MQTT_QOS)
        mqttc.subscribe("giirob/pr2-A1/devices/amr/status", qos=config.MQTT_QOS)
        print(f"[MQTT] Suscrito a:\n"
              f"  {config.TOPIC_ROBODK_ACTION}\n"
              f"  {config.TOPIC_COBOT_ACTION}")
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


mqttc = mqtt.Client(client_id=config.CLIENT_ID)
mqttc.on_connect    = on_connect
mqttc.on_message    = on_message
mqttc.on_disconnect = on_disconnect

if config.MQTT_QOS and hasattr(config, "MQTT_USER") and config.MQTT_USER:
    mqttc.username_pw_set(username=config.MQTT_USER, password=config.MQTT_PASSWORD)

mqttc.connect(config.BROKER, config.PORT, keepalive=60)
mqttc.loop_forever()
