from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
from robolink import *
RDK = robolink.Robolink()

import random, math

colors = {
	"red": [1.0, 0.0, 0.0, 1.0],
	"green": [0.0, 1.0, 0.0, 1.0],
	"blue": [0.0, 0.0, 1.0, 1.0],
	"yellow": [1.0, 1.0, 0.0, 1.0],
	"orange": [1.0, 0.5, 0.0, 1.0],
	"white": [1.0, 1.0, 1.0, 1.0]
} 

tapon_template = RDK.Item('tapa_template')
estacion_frame = RDK.Item('Frame Cinta', ITEM_TYPE_FRAME)

#Función de spawn de tapones / tapas
def spawn_tapon(color, cap_id):
	tapon_template.Copy()
	tapon_nuevo = tapon_template.Paste()
	tapon_nuevo.setParentStatic(estacion_frame) 
	tapon_nuevo.setName(cap_id)
	y = random.uniform(-184.416, 255.584)
	tapon_nuevo.setPoseAbs(robomath.transl(-5526.352, y, 1455.871) * robomath.roty(-math.pi/2))
	tapon_nuevo.setColor(colors[color])
	tapon_nuevo.setVisible(True)

