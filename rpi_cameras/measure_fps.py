#!/usr/bin/env python3
"""
Quick MJPEG frame-rate probe.

Usage:
    tests/webrtc/measure_fps.py http://127.0.0.1:18081/stream.mjpg --frames 150
"""
import argparse
import time

import requests


def parse_args():
    parser = argparse.ArgumentParser(description="Measure MJPEG stream frame rate.")
    parser.add_argument("url", help="MJPEG stream URL (e.g. http://pi:8081/stream.mjpg)")
    parser.add_argument("--frames", type=int, default=150, help="Number of frames to observe")
    parser.add_argument("--timeout", type=float, default=10.0, help="Maximum measurement time in seconds")
    return parser.parse_args()


def main():
    args = parse_args()
    resp = requests.get(args.url, stream=True, timeout=args.timeout)
    boundary = "--FRAME"
    ctype = resp.headers.get("Content-Type", "")
    if "boundary=" in ctype:
        boundary = "--" + ctype.split("boundary=")[-1]

    buf = b""
    timestamps = []
    start = time.time()

    for chunk in resp.iter_content(chunk_size=4096):
        if not chunk:
            break
        buf += chunk
        while True:
            idx = buf.find(boundary.encode())
            if idx == -1:
                break
            timestamps.append(time.time())
            buf = buf[idx + len(boundary):]
            if len(timestamps) >= args.frames:
                break
        if len(timestamps) >= args.frames or (time.time() - start) > args.timeout:
            break

    resp.close()

    if len(timestamps) < 2:
        raise SystemExit("Not enough frames captured to estimate FPS.")

    intervals = [t2 - t1 for t1, t2 in zip(timestamps, timestamps[1:])]
    avg_interval = sum(intervals) / len(intervals)
    fps = 1.0 / avg_interval if avg_interval else float("inf")
    print(f"Captured {len(timestamps)} frames in {timestamps[-1]-timestamps[0]:.2f}s -> {fps:.2f} FPS")


if __name__ == "__main__":
    main()
