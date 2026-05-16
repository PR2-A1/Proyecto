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
EMPTY_BOX_NAME = 'caja_vacia'
AMR_NAME = 'MiR100'
STATION_FRAME_NAME = 'frame_spawn_objetos'
RED_FILLED_BOX_TEMPLATE_NAME = 'caja_roja_template'
GREEN_FILLED_BOX_TEMPLATE_NAME = 'caja_verde_template'
BLUE_FILLED_BOX_TEMPLATE_NAME = 'caja_azul_template'
YELLOW_FILLED_BOX_TEMPLATE_NAME = 'caja_amarilla_template'
WHITE_FILLED_BOX_TEMPLATE_NAME = 'caja_blanca_template'
ORANGE_FILLED_BOX_TEMPLATE_NAME = 'caja_naranja_template'

#ROBOT CONFIGURATION
amr = RDK.Item(AMR_NAME, ITEM_TYPE_ROBOT)

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
		 
empty_box = RDK.Item(EMPTY_BOX_NAME, ITEM_TYPE_OBJECT)


	

def check_position(mqtt, payload):
	location = payload.get("location", "").lower()
	
	for i in range(0, 6):
		if location == locations[i].Name():
			if amr.Pose() == locations[i].Pose():
				spawn_filled_box(location)
				amr.AttachClosest()
	
	if location == place_target.Name():
		amr.DetachAll()
		time.sleep(15)
		amr.AttachClosest()
			
			
def spawn_filled_box(location):
	
	for i in range(0, 6):
		if location == locations[i].Name():
			box_templates[i].Copy()
			new_box = box_templates[i].Paste()
			new_box.setParentStatic(station_frame)
			new_box.setName("caja_llena")
			new_box.setPoseAbs(locations[i].PoseAbs() * robomath.rotz(-90 * math.pi / 180) * robomath.rotx(90 * math.pi / 180))
			empty_box.Delete()
			new_box.setVisible(True)
