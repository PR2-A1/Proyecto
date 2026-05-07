from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
import math
RDK = robolink.Robolink()

#NAMES CONFIGURATION
EXTERNAL_AXIS_NAME = 'Gudel TMF-2'
COBOT_NAME = 'ABB CRB 15000 10'
ZONE_1_NAME = 'zona_paletizado_1'
ZONE_2_NAME = 'zona_paletizado_2'
ZONE_3_NAME = 'zona_paletizado_3'
EXTERNAL_AXIS_BASE_NAME = 'Gudel TMF-2 Base'
COBOT_BASE = 'ABB CRB 15000 10 Base'
PLACE_FRAME_NAME = 'frame_place_cobot'
PRE_PLACE_NAME = 'pre_place_cobot'
PLACE_NAME = 'place_cobot'
POST_PLACE_NAME = 'post_place_cobot'
PRE_PICK_NAME = 'pre_pick_cobot'
PICK_NAME = 'pick_cobot'
POST_PICK_NAME = 'post_pick_cobot'
HOME_COBOT_TARGET_NAME = 'home_cobot'

#OBJECTS DEFINITION
external_axis = RDK.Item(EXTERNAL_AXIS_NAME, ITEM_TYPE_ROBOT)
cobot = RDK.Item(COBOT_NAME, ITEM_TYPE_ROBOT)
tool = RDK.Item(TOOL_NAME, ITEM_TYPE_ROBOT)

#TARGETS DEFINITION
zone_1 = RDK.Item(ZONE_1_NAME, ITEM_TYPE_TARGET)
zone_2 = RDK.Item(ZONE_2_NAME, ITEM_TYPE_TARGET)
zone_3 = RDK.Item(ZONE_3_NAME, ITEM_TYPE_TARGET)
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
box_offset = 520.0
box_width = 440.0
box_height = 440.0

#Function to move the external axis to the paletizing zone
def zone_palletizing(palletizing_zone, box_iteration, color):
	external_axis.MoveL(palletizing_zone)
	direction = 0
	
	if color = 'red' or color = 'green' or color = 'blue'
		place_frame.setPose(place_frame.Pose() * robomath.rotz(-90 * math.pi / 180)
		direction = -1
	if color = 'yellow' or color = 'orange' or color = 'white'
		place_frame.setPose(place_frame.Pose() * robomath.rotz(90 * math.pi / 180)
		direction = 1
	
	x = 170.0 #FIXED POSITION FOR THE X AXIS
	y = direction * (box_offset + box_width * (box_iteration % 2))
	z = box_height * int(box_iteration / 2)
	place_frame.setPos([x, y, z])
	
	#PALETIZING CYCLE
	cobot.setPoseFrame(place_frame)
	
	cobot.MoveJ(pre_place_target)
	cobot.MoveJ(place_target)
	
	tool.DetachClosest()
	
	cobot.MoveL(post_place_target)
	
	cobot.setPoseFrame(cobot_base)
	cobot.MoveJ(home_cobot)
	
def pick():
	cobot.setPoseFrame(pick_frame)
	
	cobot.MoveJ(pre_pick_cobot)
	cobot.MoveL(pick_cobot)
	
	tool.AttachClosest()
	cobot.MoveL(post_pick_cobot)
	

#MAIN LOOP
while 1:
	
