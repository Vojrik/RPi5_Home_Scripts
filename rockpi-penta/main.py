#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
import sys
import signal

import misc
import oled

def _stop(signum, frame):
    raise SystemExit

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def main():
    lock = threading.Lock()
    oled.welcome()
    try:
        # Only the OLED; no keypad or fan logic
        while True:
            try:
                oled.auto_slider(lock)   # returns immediately when slider.auto is False
                time.sleep(2)            # keep the process alive
            except Exception:
                time.sleep(1)
    finally:
        try:
            oled.goodbye()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception:
        try:
            oled.goodbye()
        except Exception:
            pass
        sys.exit(1)
