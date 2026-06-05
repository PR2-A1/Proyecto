from robodk import robolink    # RoboDK API
from robodk import robomath    # Robot toolbox
RDK = robolink.Robolink()

from robodk import *      # RoboDK API
from robolink import *    # Robot toolbox

robolink.import_install('cv2', 'opencv-python', RDK)
robolink.import_install('numpy', RDK)
import numpy as np
import cv2 as cv

#CONFIGURATION
PIXEL_SIZE = 0.457050  # mm/pixel
W_PIXELS = 1020
H_PIXELS = 1080

CAMERA_NAME = 'Camera'
CAMERA_PARAMETERS = 'SIZE=640*480'
WINDOW_NAME = 'OpenCV color recognition'

cam_item = RDK.Item(CAMERA_NAME, robolink.ITEM_TYPE_CAMERA)
if not cam_item.Valid():
	print("Camara no valida")
cam_item.setParam('Open', 1)

#FILTERING HSV COLORS
blue_hsv = np.array([120, 255, 255])
green_hsv = np.array([60, 255, 255])
red_hsv = np.array([0, 255, 255])
white_hsv = np.array([0, 0, 255])
yellow_hsv = np.array([30, 255, 255])
orange_high = np.array([25, 255, 255])
orange_low = np.array([5, 100, 100])


while cam_item.setParam('isOpen') == '1':
	#TAKE A FRAME
	bgr_image = None
	bytes_img = RDK.Cam2D_Snapshot('', cam_item)
	
	if isinstance(bytes_img, bytes) and bytes_img != b'':
	
		nparr = np.frombuffer(bytes_img, np.uint8)
		bgr_image = cv.imdecode(nparr, cv.IMREAD_COLOR)
	
	if bgr_image is None:
		break
	
	#CONVERT THE FRAME FROM BGR TO HSV	
	hsv = cv.cvtColor(bgr_image, cv.COLOR_BGR2HSV)
	
	#BLUR THE IMAGE TO FILTER NOISE
	hsv = cv.GaussianBlur(hsv,(5,5),0)
	
	#CALCULATE EACH COLOR MASK
	blue_mask = cv.inRange(hsv, blue_hsv, blue_hsv)
	green_mask = cv.inRange(hsv, green_hsv, green_hsv)
	red_mask = cv.inRange(hsv, red_hsv, red_hsv)
	white_mask = cv.inRange(hsv, white_hsv, white_hsv)
	yellow_mask = cv.inRange(hsv, yellow_hsv, yellow_hsv)
	orange_mask = cv.inRange(hsv, orange_low, orange_high)
	
	#CHECK WHAT COLOR IS THE CAP BY COUNTING ALL NON-ZERO BITS IN EACH MASK
	if cv.countNonZero(blue_mask) > 1:
		RDK.setParam('color', 'blue')
	elif cv.countNonZero(green_mask) > 1:
		RDK.setParam('color', 'green')
	elif cv.countNonZero(red_mask) > 1:
		RDK.setParam('color', 'red')
	elif cv.countNonZero(white_mask) > 1:
		RDK.setParam('color', 'white')
	elif cv.countNonZero(yellow_mask) > 1:
		RDK.setParam('color', 'yellow')
	elif cv.countNonZero(orange_mask) > 1:
		RDK.setParam('color', 'orange')
	
	#COMBINE ALL MASKS INTO ONE 
	mask = blue_mask + green_mask + red_mask + white_mask + yellow_mask + orange_mask
	
	res = cv.bitwise_and(bgr_image, bgr_image, mask = mask)
	
	#CONTOUR AND CENTER CALCULATION
	contours, hierarchy = cv.findContours(mask, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)
	if contours:
		cnt = contours[0] #WE SELECT THE FIRST CONTOUR AVAILABLE
		
		(x,y), radius = cv.minEnclosingCircle(cnt)
		
		center = (int(x), int(y))
		radius = int(radius)
		cv.circle(res, center, radius, (150, 150, 150), 2)
		
		img_height, img_width = bgr_image.shape[:2]
		
		x_mm = (float(x) - (img_width / 2.0)) * PIXEL_SIZE
		y_mm = (float(y) - (img_height / 2.0)) * PIXEL_SIZE
		
		#COMMUNICATE TO THE STATION WHERE THE CENTER OF THE CAP IS
		RDK.setParam('camera_x', x_mm)
		RDK.setParam('camera_y', y_mm)
	
	else:
		RDK.setParam('camera_x', 'none')
		RDK.setParam('camera_y', 'none')
		RDK.setParam('color', 'none')
	del contours
	cv.imshow(WINDOW_NAME, res)
	key = cv.waitKey(5)
	if key == 27:
		break #User pressed ESC, exit
			
cv.destroyAllWindows()
RDK.Cam2D_Close(cam_item)
