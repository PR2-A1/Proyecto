#!/usr/bin/env python3
"""
RGB color calibrator for physical caps on a white background.

Automatically detects the largest non-white blob in the frame, computes its
mean color and lets you accumulate several samples of the same cap (different
angles/lighting) into a per-color list. The detector then classifies a blob
by the nearest-sample rule, so a list of samples acts as an effective range
in color space — much more tolerant than a single point.

Keys:
  s  add the current mean color of the detected blob as a new sample
  r  reset the sample list for the current color (in memory)
  q  quit

Usage:
  python3 tapon_color_calibrator.py --color blue
  python3 tapon_color_calibrator.py --color red --output colors.yaml --camera 0
"""

import argparse
import os
import sys

import cv2
import numpy as np

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Same function as in the detector.
def segment_non_white(frame, sat_threshold, val_threshold):
    """Binary mask of non-white pixels: high saturation or low brightness."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    mask = ((s > sat_threshold) | (v < val_threshold)).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask

# Loads the existing samples for the given color from the YAML file, if it exists.
def load_existing_samples(path, color):
    """Read existing samples for `color` from the YAML file, if any."""
    if not (YAML_AVAILABLE and os.path.exists(path)):
        return []
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    val = data.get('colors', {}).get(color)
    if val is None:
        return []
    # Accept legacy single-triplet form as well as list-of-triplets.
    if val and isinstance(val[0], (list, tuple)):
        return [tuple(int(c) for c in s) for s in val]
    return [tuple(int(c) for c in val)]

# Saves the samples for the given color into the YAML file, preserving any existing data for other colors.
def save_samples(path, color, samples):
    """Persist the full sample list for `color` into the YAML file."""
    if not YAML_AVAILABLE:
        print('PyYAML not installed: pip install pyyaml', file=sys.stderr)
        return
    data = {'colors': {}}
    if os.path.exists(path):
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {'colors': {}}
            data.setdefault('colors', {})
    data['colors'][color] = [[int(s[0]), int(s[1]), int(s[2])] for s in samples]
    with open(path, 'w') as f:
        yaml.safe_dump(data, f, sort_keys=False)
    print(f'Saved "{color}" with {len(samples)} samples -> {path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--color', type=str, required=True,
                        help='Color name to calibrate (key in the YAML file)')
    parser.add_argument('--output', type=str, default='colors.yaml')
    parser.add_argument('--sat-threshold', type=int, default=60)
    parser.add_argument('--val-threshold', type=int, default=80)
    parser.add_argument('--min-area', type=int, default=400)
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f'Could not open camera {args.camera}', file=sys.stderr)
        sys.exit(1)

    # Start from whatever was previously saved for this color so the user can
    # extend an existing calibration instead of starting from scratch.
    samples = load_existing_samples(args.output, args.color)
    last_rgb = None
    # Min/max area seen during the session — for reference ofr the detector only, not saved.
    seen_area_min = None
    seen_area_max = None
    print(f'Calibrating "{args.color}". Existing samples loaded: {len(samples)}.')
    print('Press s to add a sample, r to reset, q to save & quit.')

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        mask = segment_non_white(frame, args.sat_threshold, args.val_threshold)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) >= args.min_area]

        if contours:
            # Largest blob: assumed to be the cap.
            c = max(contours, key=cv2.contourArea)
            blob_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.drawContours(blob_mask, [c], -1, 255, thickness=cv2.FILLED)
            # cv2.mean returns RGB; convert to RGB for YAML consistency with detector.
            mean_rgb = cv2.mean(frame, mask=blob_mask)[:3]
            last_rgb = (int(mean_rgb[0]), int(mean_rgb[1]), int(mean_rgb[2]))
            (x, y), r = cv2.minEnclosingCircle(c)
            # Geometric metrics: matched to the detector's filter parameters
            # so any value seen here is directly reusable as a threshold.
            area = cv2.contourArea(c)
            circularity = area / (np.pi * r * r) if r > 0 else 0.0
            # Track session min/max area as a reference for picking
            seen_area_min = area if seen_area_min is None else min(seen_area_min, area)
            seen_area_max = area if seen_area_max is None else max(seen_area_max, area)
            # Drawing a circle with the color and the area.
            cv2.circle(frame, (int(x), int(y)),
                       int(r), tuple(int(v) for v in mean_rgb), 2)
            cv2.putText(frame, f'mean RGB: {last_rgb}',
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0), 2)
            cv2.putText(frame,
                        f'area: {int(area)} px^2   circ: {circularity:.2f}',
                        (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 255, 255), 2)
            cv2.putText(frame,
                        f'session area min/max: {int(seen_area_min)} / {int(seen_area_max)}',
                        (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 200, 200), 1)
        else:
            cv2.putText(frame, 'no blob (move the cap closer)',
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 0, 255), 2)
        # Info and instructions.
        cv2.putText(frame,
                    f'color: {args.color}   samples: {len(samples)}',
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, 's: add sample   r: reset   q: save & quit',
                    (10, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow('Cap color calibrator', frame)
        cv2.imshow('mask', mask)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        # Saving a sample
        elif key == ord('s'):
            if last_rgb is None:
                print('No blob detected, sample not added.')
            else:
                samples.append(last_rgb)
                print(f'Added sample {last_rgb} (total: {len(samples)})')
        elif key == ord('r'):
            samples = []
            print('Sample list reset.')

    cap.release()
    cv2.destroyAllWindows()

    if samples:
        save_samples(args.output, args.color, samples)
    else:
        print(f'No samples for "{args.color}", nothing saved.')


if __name__ == '__main__':
    main()
