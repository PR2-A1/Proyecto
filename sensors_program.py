
from robodk import robolink
from robodk import robomath
from robolink import *
RDK = Robolink()

#NAMES CONFIGURATION
CAP_SENSOR_NAME = ''
LOST_CAP_SENSOR_NAME = ''

#OBJECTS CONFIGURATION
cap_sensor = RDK.Item(CAP_SENSOR_NAME, ITEM_TYPE_OBJECT)
lost_cap_sensor = RDK.Item(LOST_CAP_SENSOR_NAME, ITEM_TYPE_OBJECT)

#AUXILIAR VARIABLES
lost_caps = RDK.getParam('lost_caps')

def get_targets():
	all_objects = RDK.ItemList(ITEM_TYPE_OBJECT)
	
	target_objects = [obj for obj in all_objects if obj.Name().startswith('T')]
	return target_objects

def detect_incoming_caps():
	caps = get_targets()
	
	for cap in caps:
		if RDK.Collision(cap_sensor, cap):
			RDK.setParam('active_cap', 'True')
			
def detect_lost_caps():
	caps = get_targets()
	
	for cap in caps:
		if RDK.Collision(cap_sensor, cap):
			lost_caps += 1
			RDK.setParam('lost_caps', lost_caps)
			
while 1:
	detect_incoming_caps()
	detect_lost_caps()
	
