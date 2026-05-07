from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
RDK = robolink.Robolink()

from robolink import *
import math
import numpy as np

#NAME CONFIGURATIONS
ROBOT_NAME = 'ABB IRB 360-1/1600 4D'
TOOL_NAME = 'RobotiQ EPick Vacuum Gripper (1 Cup)'
CAMERA_NAME = 'camera_frame'
PICK_FRAME = 'frame_pick_delta'
PRE_PICK_TARGET_NAME = 'pre_pick_delta'
PICK_TARGET_NAME = 'pick_delta'
POST_PICK_TARGET_NAME = 'post_pick_delta'
ROBOT_PARENT_FRAME_NAME = 'ABB IRB 360-1/1600 4D Base'

#OBJECTS
robot = RDK.Item(ROBOT_NAME, ITEM_TYPE_ROBOT)
tool = RDK.Item(TOOL_NAME, ITEM_TYPE_TOOL)
camera = RDK.Item(CAMERA_NAME, ITEM_TYPE_FRAME)

#FRAMES
robot_frame = RDK.Item(ROBOT_PARENT_FRAME_NAME, ITEM_TYPE_FRAME)
pick_frame = RDK.Item(PICK_FRAME, ITEM_TYPE_FRAME)
pre_pick_target = RDK.Item(PRE_PICK_TARGET_NAME, ITEM_TYPE_TARGET)
pick_target = RDK.Item(PICK_TARGET_NAME, ITEM_TYPE_TARGET)
post_pick_target = RDK.Item(POST_PICK_TARGET_NAME, ITEM_TYPE_NAME)

#CONFIGURATION
z_distance_camera_to_cap = 912.302

def pick_function():
	#CHANGE THE ROBOT'S REFERENCE FRAME TO THE PICK FRAME
	robot.setPoseFrame(pick_frame)
	
	#EXECUTE THE PICK CYCLE
	robot.MoveJ(pre_pick_target)
	robot.MoveL(pick_target)
	tool.AttachClosest("tapon_")
	robot.MoveL(post_pick_target)
	
	#CHANGE BACK TO THE ROBOT'S PARENT REFERENCE FRAME
	robot.setPoseFrame(robot_frame)
	
def place_function():
	robot.setPoseFrame(place_frame)

while 1:
	x = RDK.getParam('camera_x')
	y = RDK.getParam('camera_y')
	
	#CONVERT THE CAP POSITION FROM THE CAMERA TO THE ROBOT
	cap_camera_position = robomath.TxyzRxyz_2_Pose([float(x), float(y), z_distance_camera_to_cap, 0, 90 * math.pi / 180, -90 * math.pi / 180])
	
	camera_position = robomath.Mat(camera.PoseAbs())
	robot_position = robomath.Mat(robot.PoseAbs())
	
	cap_absolute_position = camera_position * cap_camera_position
	
	cap_robot_position = robot_position.inv() * cap_absolute_position
	
	#CHANGE THE PICK FRAME POSITION
	pick_frame.setPos(cap_robot_position.Pos())
	
	pick_function()
	
	robot.MoveJ(final_pose)
