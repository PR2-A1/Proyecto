from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
RDK = robolink.Robolink()

from robodk import *      # RoboDK API
from robolink import *    # Robot toolbox

robolink.import_install('cv2', 'opencv-python', RDK)
robolink.import_install('numpy', RDK)
import numpy as np
import cv2 as cv

CAMERA_NAME = 'Camera'
CAMERA_PARAMETERS = 'SIZE=640*480'
WINDOW_NAME = 'Camara'

cam_item = RDK.Item(CAMERA_NAME, robolink.ITEM_TYPE_CAMERA)
if not cam_item.Valid():
	print("Camara no valida")
cam_item.setParam('Open', 1)

while cam_item.setParam('isOpen') == '1':

	img_socket = None
	bytes_img = RDK.Cam2D_Snapshot('', cam_item)
	if isinstance(bytes_img, bytes) and bytes_img != b'':
		nparr = np.frombuffer(bytes_img, np.uint8)
		img_socket = cv.imdecode(nparr, cv.IMREAD_COLOR)
	if img_socket is None:
		break
		
		cv.imshow(WINDOW_NAME, img_socket)
		key = cv.wsitKey(1)
		if key == 27:
			break #User pressed ESC, exit
		if cv.getWindowProperty(WINDOW_NAME, cv.WND_PROP_VISIBLE) < 1:
			break #User killed the main window, exit
			
cv.destroyAllWindows()
RDK.Cam2D_Close(cam_item)
