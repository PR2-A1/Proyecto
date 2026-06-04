#!/usr/bin/env python3
"""
Cap color detector via webcam (white background) with MQTT publishing.

Segments non-white pixels by HSV saturation, and for each blob computes the
mean color in RGB. Compares it against a list of reference colors and picks the closest one.
Does tracking and publishes a single MQTT command per cap appearance. 
When a cap leaves the frame (track lost for N frames) it is
considered gone; if it comes back, a new command is published.

MQTT topic: giirob/pr2-A1/devices/scada/action
Payload:    {"cmd":"gen","lote_id":"","color":"<color>","quantity":"1"}

Usage:
  python3 tapon_color_detector.py
  python3 tapon_color_detector.py --config colors.yaml --camera 0
  python3 tapon_color_detector.py --mqtt-host broker.hivemq.com
"""

import argparse
import json
import sys
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# Reference colors in RGB (should be calibrated for the actual lighting).
# Each color holds a list of samples to act as a "range": the detector
# classifies a blob using the nearest sample (k-NN, k=1), so collecting a
# few captures per cap under different angles/lighting gives much more
# tolerance than a single point.
# Can be overridden from a YAML file with --config.
DEFAULT_REFS_RGB = {
    'blue':   [( 60,  60, 200)],
    'green':  [( 60, 180,  60)],
    'red':    [( 40,  40, 200)],
    'yellow': [( 40, 220, 230)],
    'orange': [( 30, 130, 230)],
    # 'white' omitted as it matches the background.
}


def load_refs(path):
    """Load reference colors from a YAML file.

    Accepts both legacy single-triplet form and the new list-of-samples form:

      colors:
        blue: [60, 60, 200]                # legacy: one sample
        red:  [[40, 40, 200], [50, 45, 210]]  # multiple samples
    """
    if not YAML_AVAILABLE:
        print('PyYAML not installed, ignoring --config', file=sys.stderr)
        return DEFAULT_REFS_RGB
    # Get the YAML file content
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    # Normalise: every color ends up as a list of (R, G, B) integer tuples.
    out = {}
    for name, val in data.get('colors', {}).items():
        if val and isinstance(val[0], (list, tuple)):
            samples = [tuple(int(c) for c in s) for s in val]
        else:
            samples = [tuple(int(c) for c in val)]
        out[name] = samples
    return out

# Lab is used as a perceptually uniform color space, so Euclidean distance corresponds
# better to human perception than in RGB. OpenCV uses L in [0,255], a,b in [0,255] with 128 as zero, so we don't need to do any scaling here.
def rgb_to_lab(rgb):
    """Convert an RGB tuple (or 1x1x3 array) to Lab. Returns float32 (3,)."""
    arr = np.uint8([[list(rgb)]])
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)[0, 0]
    return lab.astype(np.float32)


def nearest_color(mean_rgb, refs_lab, max_dist):
    """Return (name, distance) of the closest reference sample in Lab space.

    refs_lab is a flat list of (color_name, lab_array) pairs, with possibly
    several entries per color (k-NN, k=1). If the closest distance exceeds
    max_dist (max variance permitted), returns (None, distance).
    """
    lab = rgb_to_lab(mean_rgb)
    # best_name refers to the closest color name, best_d is the smallest distance found.
    best_name, best_d = None, float('inf')
    # Iterate over every sample of every reference color and keep the closest one.
    for name, ref in refs_lab:
        # linalg.norm computes the Euclidean distance between the input Lab color and the reference Lab color.
        d = float(np.linalg.norm(lab - ref))
        # If this distance is smaller than the best distance found so far, we update best_name and best_d to this sample's name and distance.
        if d < best_d:
            best_name, best_d = name, d
    # If we found a closest color but its distance exceeds the max_dist threshold, we consider it as no match and return None for the name.
    if best_d > max_dist:
        return None, best_d
    return best_name, best_d


def segment_non_white(frame, sat_threshold, val_threshold):
    """Binary mask of non-white pixels: high saturation or low brightness."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Saturation (s), value (v), hue (h), hue is not used as white can have any hue, but it must have low saturation or low value.
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    # If a pixel saturation or value is above the threshold, it is considered non-white and included in the mask.
    mask = ((s > sat_threshold) | (v < val_threshold)).astype(np.uint8) * 255
    # Remove noise and fill gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def find_points(mask, frame, min_area, max_area, min_circularity):
    """Return a list of (cx, cy, r, mean_rgb) for each valid contour.
    Filters contours by area and circularity, and computes the mean RGB color inside the contour.
    
    This makes possible to filter out non-cap blolbs as we can change the min_area, max_area and min_circularity
    parameters to only accept blobs that are similar in size and shape to the caps we want to detect.
    """
    # After aplying the mask to the frame, we find contours in the binary mask. Each contour corresponds to a connected component of non-white pixels.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points = []
    # Iterate over each contour and apply the filters based on area and circularity.
    for c in contours:
        # Get the area of the blob
        area = cv2.contourArea(c)
        # Check if it corresponds to a cap.
        if area < min_area or area > max_area:
            continue
        # Get the center and radius of the minimum enclosing circle of the contour, which gives us an estimate of the blob's size and position.
        (x, y), r = cv2.minEnclosingCircle(c)
        # Check if it is circular.
        if r <= 0:
            continue
        # Get how circular the blob is
        circularity = area / (np.pi * r * r)
        # If the circularity is below the minimum threshold, we discard this blob as it is not circular enough to be a cap.
        if circularity < min_circularity:
            continue
        # Mean color inside the contour (not the bounding box).
        # blob_mask is a binary mask where the pixels inside the contour are set to 255 (white) and the rest are 0 (black). This allows us to compute the mean color only for the pixels that belong to the blob.
        blob_mask = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(blob_mask, [c], -1, 255, thickness=cv2.FILLED)
        # We get the mean color of the pixels, [:3] is used for ignoring the alpha channel. 
        mean = cv2.mean(frame, mask=blob_mask)[:3]
        points.append((int(x), int(y), int(r), tuple(int(v) for v in mean)))
    return points


class Track:
    """Tracking for one cap."""
    _next_id = 0

    def __init__(self, color, cx, cy, r):
        self.id = Track._next_id
        Track._next_id += 1
        self.color = color
        self.cx, self.cy, self.r = cx, cy, r
        self.lost = 0

    def update(self, cx, cy, r):
        self.cx, self.cy, self.r = cx, cy, r
        self.lost = 0

def match_tracks(tracks, detections, max_dist):
    """Greedy match of detections to existing tracks (same color, by distance)."""
    unmatched = list(range(len(detections)))
    for tr in tracks:
        best, best_d = -1, max_dist
        for i in unmatched:
            color, (cx, cy, _, _) = detections[i]
            if color != tr.color:
                continue
            # Compute the distance between the track's current position and the detection's position. 
            # If this distance is smaller than the best distance found so far, 
            # we update best and best_d to this detection's index and distance.
            d = float(np.hypot(cx - tr.cx, cy - tr.cy))
            if d < best_d:
                best, best_d = i, d
        # If we found a closest detection for this track and its distance is within the max_dist threshold, 
        # we consider it a match and update the track's position with the detection's position. 
        # We also remove this detection from the unmatched list, as it has been assigned to a track.
        if best >= 0:
            _, (cx, cy, r, _) = detections[best]
            tr.update(cx, cy, r)
            unmatched.remove(best)
        else:
            tr.lost += 1
    return unmatched


def main():
    # Argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera', type=int, default=1)
    parser.add_argument('--config', type=str, default=None,
                        help='YAML file with reference colors (RGB)')
    parser.add_argument('--mqtt-host', type=str, default='broker.hivemq.com')
    parser.add_argument('--mqtt-port', type=int, default=1883)
    parser.add_argument('--topic', type=str,
                        default='giirob/pr2-A1/devices/scada/action')
    parser.add_argument('--sat-threshold', type=int, default=60,
                        help='Minimum saturation to consider a pixel non-white')
    parser.add_argument('--val-threshold', type=int, default=80,
                        help='Brightness below which a pixel is also non-white')
    parser.add_argument('--min-area', type=int, default=400)
    parser.add_argument('--max-area', type=int, default=80000)
    parser.add_argument('--min-circularity', type=float, default=0.85)
    parser.add_argument('--max-color-dist', type=float, default=40.0,
                        help='Maximum Lab distance to accept a color match')
    parser.add_argument('--max-track-dist', type=float, default=80.0)
    parser.add_argument('--max-lost-frames', type=int, default=8)
    parser.add_argument('--no-window', action='store_true')
    args = parser.parse_args()

    # Load reference colors from config or default if there is no YAML file.
    refs_rgb = load_refs(args.config) if args.config else DEFAULT_REFS_RGB
    # Precompute Lab values: flat list of (name, lab_array), one entry per sample.
    refs_lab = [(name, rgb_to_lab(rgb))
                for name, samples in refs_rgb.items()
                for rgb in samples]
    print(f'Reference colors: '
          f'{ {n: len(s) for n, s in refs_rgb.items()} } (samples per color)')

    # MQTT
    client = mqtt.Client(client_id='bottlecap_color_detector', clean_session=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        client.connect_async(args.mqtt_host, args.mqtt_port, keepalive=60)
        client.loop_start()
        print(f'MQTT connecting to {args.mqtt_host}:{args.mqtt_port}')
    except Exception as e:
        print(f'MQTT connect failed: {e}', file=sys.stderr)

    def publish(color):
        payload = json.dumps({
            'cmd': 'gen', 'lote_id': '', 'color': color, 'quantity': '1'})
        client.publish(args.topic, payload, qos=1)
        print(f'[{time.strftime("%H:%M:%S")}] PUBLISH {args.topic} -> {payload}')

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f'Could not open camera {args.camera}', file=sys.stderr)
        sys.exit(1)

    tracks = []
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            mask = segment_non_white(frame, args.sat_threshold, args.val_threshold)
            points = find_points(mask, frame, args.min_area, args.max_area,
                               args.min_circularity)

            # Detections: (color, (cx, cy, r, mean_rgb)). Drop points whose
            # color does not match any reference within max_color_dist.
            detections = []
            for cx, cy, r, mean_rgb in points:
                name, _ = nearest_color(mean_rgb, refs_lab, args.max_color_dist)
                if name is None:
                    continue
                detections.append((name, (cx, cy, r, mean_rgb)))

            unmatched = match_tracks(tracks, detections, args.max_track_dist)

            for i in unmatched:
                color, (cx, cy, r, _) = detections[i]
                tracks.append(Track(color, cx, cy, r))
                publish(color)

            tracks = [t for t in tracks if t.lost <= args.max_lost_frames]

            if not args.no_window:
                for color, (cx, cy, r, mean_rgb) in detections:
                    cv2.circle(frame, (cx, cy), r, mean_rgb, 2)
                    cv2.putText(frame, color, (cx - r, cy - r - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, mean_rgb, 2)
                cv2.putText(frame,
                            f'live tracks: {sum(1 for t in tracks if t.lost == 0)}',
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 255, 0), 2)
                cv2.imshow('Cap color detector', frame)
                cv2.imshow('mask', mask)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
