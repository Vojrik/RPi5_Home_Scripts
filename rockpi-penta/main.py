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
        # jen OLED; žádné klávesy ani fan
        while True:
            try:
                oled.auto_slider(lock)   # když je slider.auto False, vrátí se hned
                time.sleep(2)            # drž proces naživu
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
