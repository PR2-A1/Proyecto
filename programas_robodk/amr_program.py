from robodk import robolink
from robodk import robomath
from robolink import *
import time, math
RDK = Robolink()

#NAMES CONFIGURATION
RED_HOPPER_TARGET_NAME = 'tolva_rojo'
BLUE_HOPPER_TARGET_NAME = 'tolva_azul'
YELLOW_HOPPER_TARGET_NAME = 'tolva_amarillo'
GREEN_HOPPER_TARGET_NAME = 'tolva_verde'
WHITE_HOPPER_TARGET_NAME = 'tolva_blanco'
ORANGE_HOPPER_TARGET_NAME = 'tolva_naranja'
PLACE_TARGET_NAME = 'place_mir100'
AMR_NAME = 'MiR' #THE ROBOT ITEM IS CALLED 'MiR' ('MiR100 Base' IS THE FRAME)
STATION_FRAME_NAME = 'frame_spawn_objetos'
RED_FILLED_BOX_TEMPLATE_NAME = 'caja_roja_template'
GREEN_FILLED_BOX_TEMPLATE_NAME = 'caja_verde_template'
BLUE_FILLED_BOX_TEMPLATE_NAME = 'caja_azul_template'
YELLOW_FILLED_BOX_TEMPLATE_NAME = 'caja_amarilla_template'
WHITE_FILLED_BOX_TEMPLATE_NAME = 'caja_blanca_template'
ORANGE_FILLED_BOX_TEMPLATE_NAME = 'caja_naranja_template'
TOOL_NAME = 'Tool3'

#ROBOT CONFIGURATION
amr = RDK.Item(AMR_NAME, ITEM_TYPE_ROBOT)
tool = RDK.Item(TOOL_NAME, ITEM_TYPE_TOOL)

#TARGETS CONFIGURATION
locations = [RDK.Item(RED_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET),     RDK.Item(BLUE_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET),
	     RDK.Item(YELLOW_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET), RDK.Item(GREEN_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET),
	     RDK.Item(WHITE_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET), RDK.Item(ORANGE_HOPPER_TARGET_NAME, ITEM_TYPE_TARGET)]

place_target = RDK.Item(PLACE_TARGET_NAME, ITEM_TYPE_TARGET)

#FRAMES CONFIGURATION
station_frame = RDK.Item(STATION_FRAME_NAME, ITEM_TYPE_FRAME)

#OBJECTS CONFIGURATION
box_templates = [RDK.Item(RED_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT),     RDK.Item(BLUE_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT),
		 RDK.Item(YELLOW_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT), RDK.Item(GREEN_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT),
		 RDK.Item(WHITE_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT), RDK.Item(ORANGE_FILLED_BOX_TEMPLATE_NAME, ITEM_TYPE_OBJECT)]

ARRIVAL_TOLERANCE_MM = 400.0 #NEIGHBOUR HOPPERS ARE ~790mm APART

#POSE OF THE BOX ON THE AMR DECK (CAPTURED FROM A CORRECTLY LOADED BOX)
box_carry_pose = robomath.Mat([
	[ 0.0, 0.0, -1.0, -15.2],
	[-1.0, 0.0,  0.0,  39.8],
	[ 0.0, 1.0,  0.0,  17.5],
	[ 0.0, 0.0,  0.0,   1.0]
])

def carried_boxes():
	"""Boxes currently loaded on the AMR deck."""
	boxes = []
	for child in tool.Childs():
		try:
			if 'caja' in child.Name().lower():
				boxes.append(child)
		except Exception:
			pass #THE ITEM WAS DELETED BY ANOTHER PROGRAM
	return boxes

def attach_box_to_amr(box):
	"""Load a box on the AMR deck regardless of where it is."""
	box.setParentStatic(tool)
	box.setPose(box_carry_pose)

def find_closest_empty_box():
	"""Find the closest empty box: visible, not a template/pallet and not held by another tool."""
	tool_pos = tool.PoseAbs().Pos()
	closest = None
	closest_dist = -1.0
	for obj in RDK.ItemList(ITEM_TYPE_OBJECT):
		try:
			name = obj.Name().lower()
			if 'caja' not in name or 'vacia' not in name or 'template' in name or 'pallet' in name:
				continue
			if not obj.Visible():
				continue
			parent = obj.Parent()
			if parent.Valid() and parent.Type() == ITEM_TYPE_TOOL:
				continue
			pos = obj.PoseAbs().Pos()
		except Exception:
			continue #ANOTHER PROGRAM DELETED THIS ITEM WHILE ITERATING, SKIP IT
		dist = math.sqrt((pos[0] - tool_pos[0]) ** 2 + (pos[1] - tool_pos[1]) ** 2 + (pos[2] - tool_pos[2]) ** 2)
		if closest is None or dist < closest_dist:
			closest = obj
			closest_dist = dist
	return closest

def check_position(mqtt, payload):
	location = payload.get("location", "").lower()

	for i in range(0, 6):
		if location == locations[i].Name():
			#THE VEHICLE MOVES THROUGH ITS JOINTS, SO ITS POSITION IS GIVEN BY THE TOOL (amr.Pose() IS ALWAYS THE BASE)
			tool_pos = tool.PoseAbs().Pos()
			target_pos = locations[i].PoseAbs().Pos()
			dist = math.sqrt((tool_pos[0] - target_pos[0]) ** 2 + (tool_pos[1] - target_pos[1]) ** 2)
			if dist < ARRIVAL_TOLERANCE_MM:
				hopper_arrival(i)
			return

	if location == place_target.Name():
		place_arrival()

def hopper_arrival(i):
	"""At the hopper: remove the empty box brought by the AMR and load a filled box of that color."""
	carried = carried_boxes()
	if any('llena' in box.Name().lower() for box in carried):
		return #ALREADY PROCESSED (REPEATED STATUS MESSAGE)

	new_box = spawn_filled_box(i)

	#DELETE THE EMPTY BOX (OR BOXES) THE AMR WAS CARRYING
	for box in carried:
		try:
			box.Delete()
		except Exception:
			pass #ALREADY DELETED

	attach_box_to_amr(new_box)

def place_arrival():
	"""At the conveyor: leave the filled box and load the empty box that the cobot leaves."""
	carried = carried_boxes()
	if any('vacia' in box.Name().lower() for box in carried):
		return #IT ALREADY CARRIES THE BOX FOR THE NEXT TRIP (REPEATED STATUS MESSAGE)

	if carried:
		tool.DetachAll() #LEAVE THE FILLED BOX ON THE CONVEYOR

	time.sleep(15) #WAIT FOR THE COBOT TO LEAVE THE EMPTY BOX

	empty = find_closest_empty_box()
	if empty is None:
		print('WARNING: no empty box available for the AMR')
		return
	attach_box_to_amr(empty)

def spawn_filled_box(i):
	box_templates[i].Copy()
	new_box = box_templates[i].Paste()
	new_box.setParentStatic(station_frame)
	new_box.setName("caja_llena")
	new_box.setPoseAbs(locations[i].PoseAbs() * robomath.rotz(-90 * math.pi / 180) * robomath.rotx(90 * math.pi / 180))
	new_box.setVisible(True)
	return new_box
