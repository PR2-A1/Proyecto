from robodk import robolink, robomath
from robolink import *

import time

RDK = robolink.Robolink()

frame_movimiento = RDK.Item('Frame Cinta', ITEM_TYPE_FRAME)

#Parámetros de la cinta
velocidad = 5.0
posicion_actual = 0.0
posicion_maxima = 20000.0


for item in RDK.ItemList():
    if item.Name().startswith("tapon_"):
        item.Delete()


while True:
    #Movimiento cinta (creditos a ETM97)
    posicion_actual += velocidad
    frame_movimiento.setPose(robomath.transl(posicion_actual, 0.0, 0.0))
     

    if posicion_actual == posicion_maxima:
    
        RDK.Render(False)
        
        active_objects = RDK.ItemList()
        for i in active_objects:
            if i.Name().startswith("tapon_"):
                i.setPose( i.Pose() * robomath.transl(2000.0, 0.0, 0.0))
        frame_movimiento.setPose(robomath.transl(0.0, 0.0, 0.0))
        
        RDK.Render(True)
