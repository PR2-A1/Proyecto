from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
RDK = robolink.Robolink()

from robolink import *
import math
import numpy as np

ROBOT_NAME = 'ABB IRB 360-1/1600 4D'
CAMERA_NAME = 'camera_frame'

robot = RDK.Item(ROBOT_NAME, ITEM_TYPE_ROBOT)
camera = RDK.Item(CAMERA_NAME, ITEM_TYPE_FRAME)

z_distance_camera_to_cap = 1042.302

while 1:
	x = RDK.getParam('camera_x')
	y = RDK.getParam('camera_y')
	
	#CONVERT THE CAP POSITION FROM THE CAMERA TO THE ROBOT
	cap_camera_position = robomath.TxyzRxyz_2_Pose([float(x), float(y), z_distance_camera_to_cap, 0, 90 * math.pi / 180, -90 * math.pi / 180])
	
	camera_position = robomath.Mat(camera.PoseAbs())
	robot_position = robomath.Mat(robot.PoseAbs())
	
	cap_absolute_position = camera_position * cap_camera_position
	
	cap_robot_position = robot_position.inv() * cap_absolute_position
	
	final_pose = robot.Pose() # Get current orientation
	final_pose.setPos(cap_robot_position.Pos()) # Swap only the position
	
	robot.MoveJ(final_pose)
