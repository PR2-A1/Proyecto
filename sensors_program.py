
from robodk import robolink
from robodk import robomath
from robolink import *
RDK = Robolink()
import time

#NAMES CONFIGURATION
CAP_SENSOR_NAME = 'sensor_entrada_tapones'
LOST_CAP_SENSOR_NAME = 'sensor_tapones_perdidos'

#OBJECTS CONFIGURATION
cap_sensor = RDK.Item(CAP_SENSOR_NAME, ITEM_TYPE_OBJECT)
lost_cap_sensor = RDK.Item(LOST_CAP_SENSOR_NAME, ITEM_TYPE_OBJECT)

#AUXILIAR VARIABLES
lost_caps = RDK.getParam('lost_caps')

def get_targets():
	all_objects = RDK.ItemList(ITEM_TYPE_OBJECT)
	
	target_objects = [obj for obj in all_objects if obj.Name().startswith('C')]
	return target_objects

def detect_incoming_caps():
	caps = get_targets()
	
	for cap in caps:
		if RDK.Collision(cap_sensor, cap):
			RDK.setParam('active_cap', 'True')
			time.sleep(1.5)
	
	RDK.setParam('active_cap', 'False')
			
def detect_lost_caps():
	global lost_caps
	caps = get_targets()
	
	for cap in caps:
		if RDK.Collision(lost_cap_sensor, cap):
			lost_caps = lost_caps + 1
			RDK.setParam('lost_caps', lost_caps)
			
while 1:
	detect_incoming_caps()
	detect_lost_caps()
