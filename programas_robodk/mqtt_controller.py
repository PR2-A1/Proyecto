from robodk import robolink
import json
import threading
import traceback
import sys
import os

RDK = robolink.Robolink()

#PIN THE PROJECT FOLDER: RoboDK EXPORTS EMBEDDED SCRIPTS TO /tmp AND STALE COPIES THERE WOULD SHADOW THE REAL MODULES
PROJECT_DIR = '/home/enric_talens/Downloads'
sys.path.insert(0, PROJECT_DIR)

RDK.setParam("station_init", "0")

import config
import cobot_program as cp
import cap_spawn as cs
import amr_program as ap
import delta_program as dp

RDK.setParam("station_init", "1")

cm = RDK.Item("conveyor_movement", robolink.ITEM_TYPE_PROGRAM) #PROGRAM FOR CONVEYOR MOVEMENT (cm) WITHIN ROBODK

cobot_lock = threading.Lock() #ONLY ONE PALLETIZING CYCLE AT A TIME
amr_lock = threading.Lock() #SERIALIZE AMR STATUS HANDLING (IT SLEEPS WAITING FOR THE COBOT)

def run_palletizing(mqttc, payload):
	#RUNS IN ITS OWN THREAD SO THE MQTT LOOP KEEPS PROCESSING MESSAGES (E.G. CAP SPAWNS) DURING THE CYCLE
	with cobot_lock:
		try:
			cp.palletizing_cycle(mqttc, payload)
		except Exception:
			traceback.print_exc()

def run_amr(mqttc, payload):
	with amr_lock:
		try:
			ap.check_position(mqttc, payload)
		except Exception:
			traceback.print_exc()


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
		threading.Thread(
			target=run_palletizing,
			args=(mqttc, payload),
			daemon=True,
		).start()

	elif topic == "giirob/pr2-A1/devices/amr/status":
		threading.Thread(
			target=run_amr,
			args=(mqttc, payload),
			daemon=True,
		).start()

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
		
		

