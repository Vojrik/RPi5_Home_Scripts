#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import time
import errno
import subprocess
import multiprocessing as mp

import board
import busio
import adafruit_ssd1306

from PIL import Image, ImageDraw, ImageFont

import misc

# --- Global state ---
disp = None
i2c = None
_OLED_DISABLED = False
_FAILS = 0
_HARD_RESET_AFTER = 2  # escalate to a hard restart after repeated failures

# --- Fonty ---
font = {
    '10': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 10),
    '11': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 11),
    '12': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 12),
    '14': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 14),
}

# --- Fault-tolerant I2C / OLED helpers ---

def _mk_i2c():
    # Calm the bus by lowering the frequency
    return busio.I2C(board.SCL, board.SDA, frequency=100_000)

def _hard_i2c_restart():
    # Reload the drivers in case the bus is stuck
    cmds = [
        ["modprobe", "-r", "i2c_bcm2835"],
        ["modprobe", "-r", "i2c-dev"],
        ["modprobe", "i2c_bcm2835"],
        ["modprobe", "i2c-dev"],
    ]
    for c in cmds:
        try:
            subprocess.run(c, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    time.sleep(0.3)

def disp_init():
    """Initialise OLED and I2C while clearing any previous state."""
    global disp, i2c, _OLED_DISABLED
    try:
        if hasattr(disp, "poweroff"):
            disp.poweroff()
    except Exception:
        pass
    try:
        if i2c and hasattr(i2c, "deinit"):
            i2c.deinit()
    except Exception:
        pass

    disp = None
    i2c = None
    time.sleep(0.05)

    i2c = _mk_i2c()

    # Wait for the bus lock
    t0 = time.time()
    while not i2c.try_lock():
        if time.time() - t0 > 1.5:
            raise OSError("I2C busy")
        time.sleep(0.01)
    try:
        # Optionally: i2c.scan()
        pass
    finally:
        i2c.unlock()

    disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, addr=0x3C, reset=None)
    disp.fill(0)
    disp.show()
    _OLED_DISABLED = False
    return disp

def recover_oled(hard=False):
    if hard:
        _hard_i2c_restart()
    return disp_init()

def safe_disp_call(fn, *args, **kwargs):
    """Wrapper for SSD1306 calls. Retries + re-init on Errno 121/110 and TimeoutError."""
    global _FAILS, _OLED_DISABLED
    delay = 0.05
    for attempt in range(1, 4):
        try:
            if _OLED_DISABLED and attempt == 1:
                recover_oled(hard=False)
            out = fn(*args, **kwargs)
            _FAILS = 0
            _OLED_DISABLED = False
            return out

        except TimeoutError:
            _FAILS += 1
            try:
                recover_oled(hard=(_FAILS >= _HARD_RESET_AFTER))
            except Exception:
                pass
            time.sleep(delay); delay *= 2
            continue

        except OSError as e:
            err = getattr(e, "errno", None)
            if err in (121, 110):  # 121 Remote I/O, 110 timeout
                _FAILS += 1
                try:
                    recover_oled(hard=(_FAILS >= _HARD_RESET_AFTER))
                except Exception:
                    pass
                time.sleep(delay); delay *= 2
                continue
            raise

        except Exception:
            _FAILS += 1
            time.sleep(delay); delay *= 2
            continue

    _OLED_DISABLED = True
    return None

# --- Canvas initialisation ---
try:
    disp = disp_init()
except Exception:
    disp = None
    _OLED_DISABLED = True

if disp is not None:
    image = Image.new('1', (disp.width, disp.height))
else:
    # Use fallback dimensions until reinitialisation succeeds
    image = Image.new('1', (128, 32))
draw = ImageDraw.Draw(image)

# --- UI helpers ---

def disp_show():
    def _do():
        global disp, image, draw
        if disp is None:
            recover_oled(hard=False)
            if disp is None:
                return
            image = Image.new('1', (disp.width, disp.height))
            draw = ImageDraw.Draw(image)
        im = image.rotate(180) if misc.conf['oled'].get('rotate', False) else image
        disp.image(im)
        disp.show()
        draw.rectangle((0, 0, image.width, image.height), outline=0, fill=0)
    safe_disp_call(_do)

def welcome():
    draw.text((0, 0), 'ROCKPi SATA HAT', font=font['14'], fill=255)
    draw.text((32, 16), 'Loading...', font=font['12'], fill=255)
    disp_show()

def goodbye():
    draw.text((32, 8), 'Good Bye ~', font=font['14'], fill=255)
    disp_show()
    time.sleep(2)
    disp_show()  # clear

def put_disk_info():
    k, v = misc.get_disk_info()
    text1 = 'Disk: {} {}'.format(k[0], v[0])

    if len(k) == 5:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        text3 = '{} {}  {} {}'.format(k[3], v[3], k[4], v[4])
        page = [
            {'xy': (0, -2), 'text': text1, 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': text2, 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': text3, 'fill': 255, 'font': font['11']},
        ]
    elif len(k) == 3:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        page = [
            {'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': text2, 'fill': 255, 'font': font['12']},
        ]
    else:
        page = [{'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['14']}]

    return page

def gen_pages():
    pages = {
        0: [
            {'xy': (0, -2), 'text': misc.get_info('up'), 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': misc.get_cpu_temp(), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': misc.get_info('ip'), 'fill': 255, 'font': font['11']},
        ],
        1: [
            {'xy': (0, 2), 'text': misc.get_info('cpu'), 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': misc.get_info('men'), 'fill': 255, 'font': font['12']},
        ],
        2: [
            {'xy': (0, -2), 'text': misc.get_info('disk_root'), 'fill': 255, 'font': font['10']},
            {'xy': (0, 10), 'text': misc.get_info('disk_md0'),  'fill': 255, 'font': font['10']},
            {'xy': (0, 21), 'text': misc.get_info('disk_md1'),  'fill': 255, 'font': font['10']},
        ],
    }
    return pages

def slider(lock):
    with lock:
        for item in misc.slider_next(gen_pages()):
            draw.text(**item)
        disp_show()

def auto_slider(lock):
    while misc.conf['slider']['auto']:
        if _OLED_DISABLED:
            try:
                recover_oled(hard=False)
            except Exception:
                time.sleep(2)
        else:
            slider(lock)
            misc.slider_sleep()
    else:
        slider(lock)

# --- main ---
if __name__ == '__main__':
    lock = mp.Lock()
    welcome()
    try:
        auto_slider(lock)
    finally:
        goodbye()
