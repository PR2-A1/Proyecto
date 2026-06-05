from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
import paho.mqtt.client as mqtt
RDK = robolink.Robolink()
import config

from robolink import *
import math, time, json
import numpy as np

mqttc = mqtt.Client(client_id=config.CLIENT_ID + "-delta")

#NAME CONFIGURATIONS
ROBOT_NAME = 'ABB IRB 360-1/1600 4D'
TOOL_NAME = 'RobotiQ EPick Vacuum Gripper (1 Cup)'
CAMERA_NAME = 'camera_frame'
PICK_FRAME = 'frame_pick_delta'
PRE_PICK_TARGET_NAME = 'pre_pick_delta'
PICK_TARGET_NAME = 'pick_delta'
POST_PICK_TARGET_NAME = 'post_pick_delta'
ROBOT_PARENT_FRAME_NAME = 'ABB IRB 360-1/1600 4D Base'
RED_PLACE_TARGET_NAME = 'target_tolva_rojo'
GREEN_PLACE_TARGET_NAME = 'target_tolva_verde'
BLUE_PLACE_TARGET_NAME = 'target_tolva_azul'
ORANGE_PLACE_TARGET_NAME = 'target_tolva_naranja'
YELLOW_PLACE_TARGET_NAME = 'target_tolva_amarillo'
WHITE_PLACE_TARGET_NAME = 'target_tolva_blanco'
DELTA_HOME_TARGET_NAME = 'target_home_delta'

#OBJECTS
robot = RDK.Item(ROBOT_NAME, ITEM_TYPE_ROBOT)
tool = RDK.Item(TOOL_NAME, ITEM_TYPE_TOOL)
camera = RDK.Item(CAMERA_NAME, ITEM_TYPE_FRAME)

#FRAMES
robot_frame = RDK.Item(ROBOT_PARENT_FRAME_NAME, ITEM_TYPE_FRAME)
pick_frame = RDK.Item(PICK_FRAME, ITEM_TYPE_FRAME)

#TARGETS
pre_pick_target = RDK.Item(PRE_PICK_TARGET_NAME, ITEM_TYPE_TARGET)
pick_target = RDK.Item(PICK_TARGET_NAME, ITEM_TYPE_TARGET)
post_pick_target = RDK.Item(POST_PICK_TARGET_NAME, ITEM_TYPE_TARGET)
red_place_target = RDK.Item(RED_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
green_place_target = RDK.Item(GREEN_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
blue_place_target = RDK.Item(BLUE_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
orange_place_target = RDK.Item(ORANGE_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
yellow_place_target = RDK.Item(YELLOW_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
white_place_target = RDK.Item(WHITE_PLACE_TARGET_NAME, ITEM_TYPE_TARGET)
delta_home = RDK.Item(DELTA_HOME_TARGET_NAME, ITEM_TYPE_TARGET)

#CONFIGURATION
z_distance_camera_to_cap = 912.302
cap_pose = robomath.Mat([[-0.0, -0.0, -1.0, 0.0],
			[0.0, -1.0, 0.0, 0.0],
			[-1.0, 0.0, 0.0, 10.0],
			[0.0, 0.0, 0.0, 1.0]])
y_offset = (3.0 * 0.36) / 0.01

def emergency_stop():
	robot.Stop()
	
def reset_emergency_stop():
	item = tool.DetachClosest()
	item.Delete()
	robot.MoveJ(delta_home, blocking = False)

def pick_function():
	global cap
	#CHANGE THE ROBOT'S REFERENCE FRAME TO THE PICK FRAME
	robot.setPoseFrame(pick_frame)
	
	#EXECUTE THE PICK CYCLE
	robot.MoveJ(pre_pick_target, blocking = False)
	robot.MoveL(pick_target, blocking = False)
	cap = tool.AttachClosest("C", 300.0)

	#IF NO CAP IS WITHIN REACH (STALE CAMERA DETECTION) ABORT THE CYCLE INSTEAD OF CRASHING
	if not cap.Valid():
		robot.setPoseFrame(robot_frame)
		robot.MoveJ(delta_home, blocking = False)
		return False

	cap.setPose(cap_pose)
	robot.MoveL(post_pick_target, blocking = False)

	#CHANGE BACK TO THE ROBOT'S PARENT REFERENCE FRAME
	robot.setPoseFrame(robot_frame)
	return True
	
def place_function(color):
	global cap
	match color:
		case 'red':
			robot.MoveJ(red_place_target, blocking = False)
		case 'green':
			robot.MoveJ(green_place_target, blocking = False)
		case 'blue':
			robot.MoveJ(blue_place_target, blocking = False)
		case 'orange':
			robot.MoveJ(orange_place_target, blocking = False)
		case 'yellow':
			robot.MoveJ(yellow_place_target, blocking = False)
		case 'white':
			robot.MoveJ(white_place_target, blocking = False)
	tool.DetachAll()
	msg = json.dumps({"status":"completed", "color":color, "id_cap":cap.Name()})
	mqttc.publish(config.TOPIC_DELTA_STATUS, msg, qos=config.MQTT_QOS)
	cap.Delete()
	
	
	
	robot.MoveJ(delta_home, blocking = False)


#MQTT CONNECTION (solo en ejecucion directa; al importarse desde mqtt_controller no se conecta)
if __name__ == "__main__":
	mqttc.connect(config.BROKER, config.PORT, keepalive=60)
	mqttc.loop_start()

#BUCLE PRINCIPAL
while RDK.getParam("station_init") == "1" or RDK.getParam("station_init") == 1:
	x = RDK.getParam('camera_x')
	y = RDK.getParam('camera_y')
	color = RDK.getParam('color')
	if x != 'none' and y != 'none' and color != 'none':
		#CONSUME THE DETECTION SO THE SAME (STALE) COORDINATES ARE NEVER USED TWICE
		RDK.setParam('camera_x', 'none')
		RDK.setParam('camera_y', 'none')
		RDK.setParam('color', 'none')

		#pick_time = time.perf_counter()
		#CONVERT THE CAP POSITION FROM THE CAMERA TO THE ROBOT
		cap_camera_position = robomath.TxyzRxyz_2_Pose([float(x), float(y) + y_offset, z_distance_camera_to_cap, 0, 90 * math.pi / 180, -90 * math.pi / 180])
		
		camera_position = robomath.Mat(camera.PoseAbs())
		robot_position = robomath.Mat(robot.PoseAbs())
		
		cap_absolute_position = camera_position * cap_camera_position
		
		cap_robot_position = robot_position.inv() * cap_absolute_position
		
		#CHANGE THE PICK FRAME POSITION
		pick_frame_pose = pick_frame.Pose()
		pick_frame_pose.setPos(cap_robot_position.Pos())
		pick_frame.setPose(pick_frame_pose)
		#place_time = time.perf_counter()
		#difference = place_time - pick_time
		#RDK.ShowMessage(f"{difference:.4f}\n")
		if pick_function():
			place_function(color)
		
		
