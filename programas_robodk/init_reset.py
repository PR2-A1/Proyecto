from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
from robolink import *    # Robot toolbox
import cobot_program as cp
import time

RDK = Robolink()

#NAMES CONFIGURATION
DELTA_NAME = 'ABB IRB 360-1/1600 4D'
COBOT_NAME = 'ABB CRB 15000 10'
EXTERNAL_AXIS_NAME = 'Gudel TMF-2'
AMR_NAME = 'MiR100'
AMR_TOOL_NAME = 'Tool3'
DELTA_PARENT_FRAME_NAME = 'ABB IRB 360-1/1600 4D Base'
COBOT_PARENT_FRAME_NAME = 'ABB CRB 15000 10 Base'
DELTA_HOME_TARGET_NAME = 'target_home_delta'
COBOT_HOME_TARGET_NAME = 'home_cobot'
EXTERNAL_AXIS_HOME_TARGET_NAME = 'zona_pick'
AMR_HOME_TARGET_NAME = 'place_mir100'
EMPTY_BOX_NAME = 'caja_vacia'

#ROBOTS AND OBJECTS CONFIGURATION
delta = RDK.Item(DELTA_NAME, ITEM_TYPE_ROBOT)
cobot = RDK.Item(COBOT_NAME, ITEM_TYPE_ROBOT)
external_axis = RDK.Item(EXTERNAL_AXIS_NAME, ITEM_TYPE_ROBOT)
amr = RDK.Item(AMR_NAME, ITEM_TYPE_ROBOT)
empty_box = RDK.Item(EMPTY_BOX_NAME, ITEM_TYPE_OBJECT)
amr_tool = RDK.Item(AMR_TOOL_NAME, ITEM_TYPE_TOOL)

#TARGETS CONFIGURATION
delta_home_target = RDK.Item(DELTA_HOME_TARGET_NAME, ITEM_TYPE_TARGET)
cobot_home_target = RDK.Item(COBOT_HOME_TARGET_NAME, ITEM_TYPE_TARGET)
external_axis_home_target = RDK.Item(EXTERNAL_AXIS_HOME_TARGET_NAME, ITEM_TYPE_TARGET)
amr_home_target = RDK.Item(AMR_HOME_TARGET_NAME, ITEM_TYPE_TARGET)

#FRAMES CONFIGURATION
delta_parent_frame = RDK.Item(DELTA_PARENT_FRAME_NAME, ITEM_TYPE_FRAME)
cobot_parent_frame = RDK.Item(COBOT_PARENT_FRAME_NAME, ITEM_TYPE_FRAME)
	
#CLEAN EVERY OBJECT USED IN PREVIOUS SESSIONS
to_delete = [item for item in RDK.ItemList(ITEM_TYPE_OBJECT)
             if item.Valid() and (item.Name().startswith("C0") or item.Name() == "caja_llena")]

for item in to_delete:
	item.Delete()


if not empty_box or not empty_box.Valid():
	cp.spawn_empty_box()

#MOVE EVERY ROBOT TO IT'S HOME POSITION
delta.setPoseFrame(delta_parent_frame)
delta.MoveJ(delta_home_target)
external_axis.MoveL(external_axis_home_target, blocking = False)
amr.MoveJ(amr_home_target, blocking = False)
if empty_box.Parent() != amr_tool:
	cp.reload_empty_box()
while cobot.Busy() or external_axis.Busy():
	time.sleep(0.05)
cobot.setPoseFrame(cobot_parent_frame)
cobot.MoveJ(cobot_home_target, blocking = False)
#ATTACH THE CLOSEST OBJECT TO THE AMR IN CASE THE BOX IT WAS CARRYING WAS DELETED
amr_tool.AttachClosest("caja_vacia", 500)
	
