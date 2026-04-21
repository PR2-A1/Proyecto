from robodk import robolink, robomath
import time
import random

# Start the RoboDK API
RDK = robolink.Robolink()

colors = [ [1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0], #Rojo, verde, azul
           [1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 1.0], [1.0, 0.5, 0.0, 1.0]] #Blanco, negro, naranja

tapon_template = RDK.Item('tapa_template')

#Función de spawn de tapones / tapas
def spawn_tapon():
    tapon_nuevo = tapon_template.Copy()
    tapon_nuevo.setName('tapon_' + str(time.time()))
    y = random.uniform(-178.0, 255.0)
    tapon_nuevo.setPose(robomath.transl(-5475.0, y, 1453.9))
    tapon_nuevo.setColor(random.choice(colors))


def main():
    while True:
        spawn_tapon()
        time.sleep(3)
