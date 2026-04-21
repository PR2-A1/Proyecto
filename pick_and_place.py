# You can also use the new version of the API:
# Type help("robodk.robolink") or help("robodk.robomath") for more information
# Press F5 to run the script
# Documentation: https://robodk.com/doc/en/RoboDK-API.html
# Reference:     https://robodk.com/doc/en/PythonAPI/robodk.html
# Note: It is not required to keep a copy of this file, your Python script is saved with your RDK project

# You can also use the new version of the API:
from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
RDK = robolink.Robolink()

# Forward and backwards compatible use of the RoboDK API:
# Remove these 2 lines to follow python programming guidelines
from robodk import *      # RoboDK API
from robolink import *    # Robot toolbox
# Link to RoboDK
# RDK = Robolink()



def function_pick(robot,pick_frame,pre_pick,pick,objeto,tool):
    robot.setFrame(pick_frame)
    robot.MoveL(pre_pick)
    robot.setSpeed(150)
    robot.MoveL(pick)
    robot.setDO(0,1) 
    robot.WaitMove(timeout=2)
    tool.AttachClosest(tolerance_mm=-1, list_objects=[objeto])  
    robot.MoveL(pre_pick)

def function_place(robot,place_frame,pre_place,place,objeto,tool):
    robot.setFrame(place_frame)
    robot.MoveL(pre_place)
    robot.setSpeed(200)
    robot.MoveL(place)
    robot.setDO(0,0)
    robot.WaitMove(timeout=1)
    tool.DetachClosest(parent=0)
    tool.DetachAll(parent=0)
    robot.setSpeed(500)
    guardar_posiciones(objeto)
    robot.MoveL(pre_place)

def guardar_posiciones(objeto):
    pose_global = objeto.PoseAbs()
    objeto.setParentStatic(objeto)
    objeto.setPoseAbs(pose_global) 