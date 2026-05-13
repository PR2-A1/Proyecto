from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
from robolink import *
import math
RDK = robolink.Robolink()

#NAMES CONFIGURATION
EXTERNAL_AXIS_NAME = 'Gudel TMF-2'
COBOT_NAME = 'ABB CRB 15000 10'
TOOL_NAME = 'SMC ZXP7A01-ZP25C-X1 Vacuum Gripper'
ZONE_1_NAME = 'zona_paletizado_1'
ZONE_2_NAME = 'zona_paletizado_2'
ZONE_3_NAME = 'zona_paletizado_3'
PICK_ZONE_NAME = 'zona_pick'
EMPTY_BOX_PICK_ZONE_NAME = 'zona_pick_caja_vacia'
EXTERNAL_AXIS_BASE_NAME = 'Gudel TMF-2 Base'
COBOT_BASE = 'ABB CRB 15000 10 Base'
PLACE_FRAME_NAME = 'frame_place_cobot'
PRE_PLACE_NAME = 'pre_place_cobot'
PLACE_NAME = 'place_cobot'
POST_PLACE_NAME = 'post_place_cobot'
PICK_FRAME_NAME = 'frame_pick_cobot'
PRE_PICK_NAME = 'pre_pick_cobot'
PICK_NAME = 'pick_cobot'
POST_PICK_NAME = 'post_pick_cobot'
HOME_COBOT_TARGET_NAME = 'home_cobot'
TEMPLATE_BOX_NAME = 'caja_template'

#OBJECTS DEFINITION
external_axis = RDK.Item(EXTERNAL_AXIS_NAME, ITEM_TYPE_ROBOT)
cobot = RDK.Item(COBOT_NAME, ITEM_TYPE_ROBOT)
tool = RDK.Item(TOOL_NAME, ITEM_TYPE_TOOL)
template_box = RDK.Item(TEMPLATE_BOX_NAME, ITEM_TYPE_OBJECT)

#TARGETS DEFINITION
#EXTERNAL AXIS TARGETS
zone_1 = RDK.Item(ZONE_1_NAME, ITEM_TYPE_TARGET)
zone_2 = RDK.Item(ZONE_2_NAME, ITEM_TYPE_TARGET)
zone_3 = RDK.Item(ZONE_3_NAME, ITEM_TYPE_TARGET)
pick_zone = RDK.Item(PICK_ZONE_NAME, ITEM_TYPE_TARGET)
empty_box_pick_zone = RDK.Item(EMPTY_BOX_PICK_NAME, ITEM_TYPE_TARGET)
#COBOT TARGETS
pre_place_target = RDK.Item(PRE_PLACE_NAME, ITEM_TYPE_TARGET)
place_target = RDK.Item(PLACE_NAME, ITEM_TYPE_TARGET)
post_place_target = RDK.Item(POST_PLACE_NAME, ITEM_TYPE_TARGET)
pre_pick_target = RDK.Item(PRE_PICK_NAME, ITEM_TYPE_TARGET)
pick_target = RDK.Item(PICK_NAME, ITEM_TYPE_TARGET)
post_pick_target = RDK.Item(POST_PICK_NAME, ITEM_TYPE_TARGET)
home_cobot = RDK.Item(HOME_COBOT_TARGET_NAME, ITEM_TYPE_TARGET)

#REFERENCE FRAMES DEFINITION
external_axis_base = RDK.Item(EXTERNAL_AXIS_BASE_NAME, ITEM_TYPE_FRAME)
cobot_base = RDK.Item(COBOT_BASE, ITEM_TYPE_FRAME)
place_frame = RDK.Item(PLACE_FRAME_NAME, ITEM_TYPE_FRAME)
pick_frame = RDK.Item(PICK_FRAME_NAME, ITEM_TYPE_FRAME)

#EXTERNAL VARIABLES
box_offset = 760.0
z_offset = 166.094
box_width = 482.723
box_height = 321.516

left_place_frame_pose = robomath.Mat([
	[ 0.0, 1.0,  0.0,   170.0],
	[ 0.0, 0.0, -1.0,  -960.0],
	[-1.0, 0.0,  0.0,     0.0],
	[ 0.0, 0.0,  0.0,     1.0]
])

right_place_frame_pose = robomath.Mat([
	[ 0.0, -1.0, 0.0,  170.0],
	[ 0.0,  0.0, 1.0, -960.0],
	[-1.0,  0.0, 0.0,    0.0],
	[ 0.0,  0.0, 0.0,    1.0]
])

full_box_pick_frame_pose = robomath.Mat([
	[ 0.0, 0.0, 1.0, 937.827],
	[ 0.0, 1.0, 0.0,   3.926],
	[-1.0, 0.0, 0.0,  91.208],
	[ 0.0, 0.0, 0.0,     1.0]
])


empty_box_pick_frame_pose = robomath.Mat([
	[ 0.0,  0.0, -1.0, -862.173],
	[ 0.0, -1.0, -0.0,    3.926],
	[-1.0,  0.0, -0.0, -166.094],
	[ 0.0,  0.0,  0.0,      1.0]
])


def palletizing_cycle(mqttc, payload):
	pallet_id = payload.get("id_pallet", 0)
	color     = payload.get("color", "").lower()
	location  = payload.get("location", "")

	#log.info("Ciclo paletizado — pallet=%d color=%s zona=%s",
	 #    pallet_id, color, location)
	iteration = 1
	
	spawn_empty_box()
	external_axis.MoveL(pick_zone)
	pick()
	
	if location == "zone_1":
		place(zone_1, color, iteration)
	elif location == "zone_2":
		place(zone_2, color, iteration)
	elif location == "zone_3":
		place(zone_3, color, iteration)
		
	external_axis.MoveL(empty_box_pick_zone)
	pick_frame.setPose(empty_box_pick_frame_pose)
	pick()
	pick_frame.setPose(full_box_pick_frame_pose)
	external_axis.MoveL(pick_zone)
	place_empty_box()
	
	publish_finished(mqttc, pallet_id)


#Function to move the external axis to the paletizing zone
def place(palletizing_zone, color, box_iteration):
	external_axis.MoveL(palletizing_zone)
	direction = 0
	
	if color == 'red' or color == 'green' or color == 'blue':
		place_frame.setPose(right_place_frame_pose)
		direction = 1
	if color == 'yellow' or color == 'orange' or color == 'white':
		place_frame.setPose(left_place_frame_pose)
		direction = -1
	
	x = 170.0 #FIXED POSITION FOR THE X AXIS
	y = direction * (box_offset + box_width * (box_iteration % 2))
	z = box_height * int(box_iteration / 2) - z_offset
	place_frame_pose = place_frame.Pose()
	place_frame_pose.setPos([x, y, z])
	place_frame.setPose(place_frame_pose)
	
	#PALETIZING CYCLE
	cobot.setPoseFrame(place_frame)
	
	cobot.MoveJ(pre_place_target)
	cobot.MoveL(place_target)
	
	tool.DetachAll()
	
	cobot.MoveL(post_place_target)
	
	cobot.setPoseFrame(cobot_base)
	cobot.MoveJ(home_cobot)
	
def pick():
	cobot.setPoseFrame(pick_frame)
	
	cobot.MoveJ(pre_pick_target)
	cobot.MoveL(pick_target)
	
	tool.AttachClosest()
	cobot.MoveL(post_pick_target)

def place_empty_box():
	cobot.setPoseFrame(pick_frame)
	
	cobot.MoveJ(pre_pick_target)
	cobot.MoveL(pick_target)
	
	tool.DettachAll()
	cobot.MoveL(post_pick_target)
	
def spawn_empty_box():
	template_box.Copy()
	empty_box = Paste()
	empty_box.setName('caja_vacia')
	empty_box.setPoseAbs(robomath.transl(7149.384, 35.618, 115.618) * robomath.rotx(math.pi / 2))
	empty_box.setVisible(True)

	

def publish_finished(mqttc, pallet_id: int):
    msg = json.dumps({"status": "COMPLETED", "id_pallet": pallet_id})
    mqttc.publish(config.TOPIC_COBOT_STATUS, msg, qos=config.MQTT_QOS)
    log.info("COMPLETED publicado — pallet_id=%d", pallet_id)	
