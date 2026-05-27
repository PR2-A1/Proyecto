from robodk import robolink
import json
import threading
import sys
import os

RDK = robolink.Robolink()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RDK.setParam("station_init", "0")

import config
import cobot_program as cp
import cap_spawn as cs
import amr_program as ap
import delta_program as dp

RDK.setParam("station_init", "1")

cm = RDK.Item("conveyor_movement", robolink.ITEM_TYPE_PROGRAM) #PROGRAM FOR CONVEYOR MOVEMENT (cm) WITHIN ROBODK


def handle_message(mqttc, topic: str, raw: str) -> None:
	try:
		payload = json.loads(raw)
	except json.JSONDecodeError:
		log.warning("JSON invalido en [%s]: %s", topic, raw)
		return

	if topic == config.TOPIC_ROBODK_ACTION:
		cmd = payload.get("cmd", "").lower()
		if cmd == "spawn":
			cap_id  = payload.get("id_cap", "")
			color   = payload.get("color", "").lower()
			threading.Thread(
				target=cs.spawn_tapon,
				args=(color, cap_id),
				daemon=True,
			).start()
		else:
			log.warning("Comando desconocido en robodk/action: %s", cmd)

	elif topic == config.TOPIC_COBOT_ACTION:
		cp.palletizing_cycle(mqttc, payload)

	elif topic == "giirob/pr2-A1/devices/amr/status":
		ap.check_position(mqttc, payload)

	elif topic == "giirob/pr2-A1/system/emergency/status":
		status = payload.get("status", "").lower()
		if status == "emergency_active":
			cp.emergency_stop()
			dp.emergency_stop()
			cm.Stop()
		elif status == "emergency_inactive":
			cp.reset_emergency_stop()
			dp.reset_emergency_stop()
			cm.RunCode()

	else:
		log.debug("Topic no gestionado: %s", topic)
		
		

