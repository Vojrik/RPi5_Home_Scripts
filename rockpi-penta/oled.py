#!/usr/bin/python3
# -*- coding: utf-8 -*-

import contextlib
import fcntl
import os
import time
import errno
import signal
import subprocess
import multiprocessing as mp
import shutil
import threading
import sys

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
_HARD_RESET_COOLDOWN_SEC = 10
_LAST_HARD_RESET_AT = 0.0
_RECOVERY_COOLDOWN_SEC = 60
_NEXT_RECOVERY_AT = 0.0
I2C_OP_TIMEOUT_SEC = float(os.environ.get("I2C_OP_TIMEOUT_SEC", "1.5"))
WATCHDOG_TIMEOUT_SEC = float(os.environ.get("WATCHDOG_TIMEOUT_SEC", "25"))
_LAST_PROGRESS_AT = time.monotonic()
OLED_I2C_FREQ_HZ = int(os.environ.get("OLED_I2C_FREQ_HZ", "50000"))

# --- Fonts ---
font = {
    '10': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 10),
    '11': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 11),
    '12': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 12),
    '14': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 14),
}

I2C_LOCK_PATH = "/home/vojrik/.i2c-1.lock"
I2C_DESIGNWARE_DEVICE = "1f00074000.i2c"

# --- Fault-tolerant I2C / OLED helpers ---

@contextlib.contextmanager
def i2c_lock(timeout=1.0):
    start = time.time()
    fd = os.open(I2C_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        os.chmod(I2C_LOCK_PATH, 0o666)
    except OSError:
        pass
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("I2C lock timeout")
                time.sleep(0.01)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _touch_progress():
    global _LAST_PROGRESS_AT
    _LAST_PROGRESS_AT = time.monotonic()


def _sleep_with_heartbeat(seconds):
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        _touch_progress()
        time.sleep(min(1.0, remaining))


def _start_watchdog():
    if WATCHDOG_TIMEOUT_SEC <= 0:
        return

    def _watchdog_loop():
        while True:
            time.sleep(2.0)
            if time.monotonic() - _LAST_PROGRESS_AT > WATCHDOG_TIMEOUT_SEC:
                print(
                    f"Watchdog: no progress for >{WATCHDOG_TIMEOUT_SEC:.0f}s, exiting for service restart.",
                    file=sys.stderr,
                )
                os._exit(1)

    thread = threading.Thread(target=_watchdog_loop, daemon=True, name="oled-watchdog")
    thread.start()


@contextlib.contextmanager
def _i2c_op_timeout(timeout_sec):
    if timeout_sec <= 0:
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise TimeoutError("I2C operation timeout")

    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, timeout_sec)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])
        signal.signal(signal.SIGALRM, old_handler)

def _mk_i2c():
    # Slower clock lowers error rate on marginal wiring/noisy bus.
    return busio.I2C(board.SCL, board.SDA, frequency=OLED_I2C_FREQ_HZ)

def _run_quiet(cmd):
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _systemctl(action, unit):
    _run_quiet(["systemctl", action, unit])

def _sysfs_write(path, value):
    try:
        with open(path, "w", encoding="ascii") as handle:
            handle.write(value)
    except Exception:
        pass

def _reset_i2c_designware():
    unbind_path = "/sys/bus/platform/drivers/i2c_designware/unbind"
    bind_path = "/sys/bus/platform/drivers/i2c_designware/bind"
    if not (os.path.exists(unbind_path) and os.path.exists(bind_path)):
        return False
    _sysfs_write(unbind_path, I2C_DESIGNWARE_DEVICE)
    time.sleep(0.05)
    _sysfs_write(bind_path, I2C_DESIGNWARE_DEVICE)
    return True

def _gpio_i2c_unstick():
    if shutil.which("pinctrl") is not None:
        # Pulse SCL while SDA is pulled up to release stuck slaves.
        _run_quiet(["pinctrl", "set", "2", "ip", "pu"])
        _run_quiet(["pinctrl", "set", "3", "op", "dh"])
        for _ in range(9):
            _run_quiet(["pinctrl", "set", "3", "op", "dl"])
            time.sleep(0.001)
            _run_quiet(["pinctrl", "set", "3", "op", "dh"])
            time.sleep(0.001)
        # STOP condition: SDA low -> high while SCL high.
        _run_quiet(["pinctrl", "set", "2", "op", "dl"])
        time.sleep(0.001)
        _run_quiet(["pinctrl", "set", "3", "op", "dh"])
        time.sleep(0.001)
        _run_quiet(["pinctrl", "set", "2", "ip", "pu"])
        _run_quiet(["pinctrl", "set", "2", "a3"])
        _run_quiet(["pinctrl", "set", "3", "a3"])
        return
    if shutil.which("raspi-gpio") is None:
        return
    # Pulse SCL while SDA is pulled up to release stuck slaves.
    _run_quiet(["raspi-gpio", "set", "2", "ip", "pu"])
    _run_quiet(["raspi-gpio", "set", "3", "op", "dh"])
    for _ in range(9):
        _run_quiet(["raspi-gpio", "set", "3", "op", "dl"])
        time.sleep(0.001)
        _run_quiet(["raspi-gpio", "set", "3", "op", "dh"])
        time.sleep(0.001)
    # STOP condition: SDA low -> high while SCL high.
    _run_quiet(["raspi-gpio", "set", "2", "op", "dl"])
    time.sleep(0.001)
    _run_quiet(["raspi-gpio", "set", "3", "op", "dh"])
    time.sleep(0.001)
    _run_quiet(["raspi-gpio", "set", "2", "ip", "pu"])

def _hard_i2c_restart():
    # On Pi 5 / RP1, unloading i2c modules can reshuffle/remove bus nodes.
    # Prefer bus-level recovery only.
    global _LAST_HARD_RESET_AT
    if os.geteuid() != 0:
        return
    now = time.time()
    if now - _LAST_HARD_RESET_AT < _HARD_RESET_COOLDOWN_SEC:
        return
    _LAST_HARD_RESET_AT = now
    _gpio_i2c_unstick()
    _reset_i2c_designware()
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

    with i2c_lock():
        with _i2c_op_timeout(I2C_OP_TIMEOUT_SEC):
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

        with _i2c_op_timeout(I2C_OP_TIMEOUT_SEC):
            disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, addr=0x3C, reset=None)
        disp.fill(0)
        disp.show()
    _touch_progress()
    _OLED_DISABLED = False
    return disp

def recover_oled(hard=False):
    if hard:
        _hard_i2c_restart()
    return disp_init()

def safe_disp_call(fn, *args, **kwargs):
    """Wrapper for SSD1306 calls. Retries + re-init on Errno 121/110 and TimeoutError."""
    global _FAILS, _OLED_DISABLED, _NEXT_RECOVERY_AT
    delay = 0.05
    for attempt in range(1, 4):
        try:
            _touch_progress()
            if _OLED_DISABLED and attempt == 1:
                recover_oled(hard=False)
            with i2c_lock():
                with _i2c_op_timeout(I2C_OP_TIMEOUT_SEC):
                    out = fn(*args, **kwargs)
            _FAILS = 0
            _OLED_DISABLED = False
            _touch_progress()
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
    _NEXT_RECOVERY_AT = time.monotonic() + _RECOVERY_COOLDOWN_SEC
    return None

# --- Canvas initialisation ---
try:
    _start_watchdog()
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
        draw.rectangle((0, 0, image.width, image.height), outline=0, fill=_bg_color())
    safe_disp_call(_do)

def _text_color():
    return 0 if misc.conf['oled'].get('invert', False) else 255

def _bg_color():
    return 255 if misc.conf['oled'].get('invert', False) else 0

def _clear_background():
    draw.rectangle((0, 0, image.width, image.height), outline=0, fill=_bg_color())

def welcome():
    _clear_background()
    draw.text((0, 0), 'ROCKPi SATA HAT', font=font['14'], fill=_text_color())
    draw.text((32, 16), 'Loading...', font=font['12'], fill=_text_color())
    disp_show()

def goodbye():
    _clear_background()
    draw.text((32, 8), 'Good Bye ~', font=font['14'], fill=_text_color())
    disp_show()
    time.sleep(2)
    disp_show()  # clear

def put_disk_info():
    k, v = misc.get_disk_info()
    text1 = 'Disk: {} {}'.format(k[0], v[0])
    text_color = _text_color()

    if len(k) == 5:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        text3 = '{} {}  {} {}'.format(k[3], v[3], k[4], v[4])
        page = [
            {'xy': (0, -2), 'text': text1, 'fill': text_color, 'font': font['11']},
            {'xy': (0, 10), 'text': text2, 'fill': text_color, 'font': font['11']},
            {'xy': (0, 21), 'text': text3, 'fill': text_color, 'font': font['11']},
        ]
    elif len(k) == 3:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        page = [
            {'xy': (0, 2), 'text': text1, 'fill': text_color, 'font': font['12']},
            {'xy': (0, 18), 'text': text2, 'fill': text_color, 'font': font['12']},
        ]
    else:
        page = [{'xy': (0, 2), 'text': text1, 'fill': text_color, 'font': font['14']}]

    return page

def gen_pages():
    text_color = _text_color()
    pages = {
        0: [
            {'xy': (0, -2), 'text': misc.get_info('up'), 'fill': text_color, 'font': font['11']},
            {'xy': (0, 10), 'text': misc.get_cpu_temp(), 'fill': text_color, 'font': font['11']},
            {'xy': (0, 21), 'text': misc.get_info('ip'), 'fill': text_color, 'font': font['11']},
        ],
        1: [
            {'xy': (0, 2), 'text': misc.get_info('cpu'), 'fill': text_color, 'font': font['12']},
            {'xy': (0, 18), 'text': misc.get_info('men'), 'fill': text_color, 'font': font['12']},
        ],
        2: [
            {'xy': (0, -2), 'text': misc.get_info('disk_root'), 'fill': text_color, 'font': font['10']},
            {'xy': (0, 10), 'text': misc.get_info('disk_md0'),  'fill': text_color, 'font': font['10']},
            {'xy': (0, 21), 'text': misc.get_info('disk_md1'),  'fill': text_color, 'font': font['10']},
        ],
    }
    return pages

def slider(lock):
    with lock:
        _clear_background()
        for item in misc.slider_next(gen_pages()):
            draw.text(**item)
        disp_show()

def _white_test(lock):
    with lock:
        draw.rectangle((0, 0, image.width, image.height), outline=0, fill=255)
        disp_show()

def auto_slider(lock):
    while True:
        _touch_progress()
        misc.reload_conf()

        if misc.conf['oled'].get('white-test', False):
            _white_test(lock)
            _sleep_with_heartbeat(misc.conf['slider'].get('time', 10.0))
            continue

        if misc.conf['slider']['auto']:
            if _OLED_DISABLED:
                if time.monotonic() >= _NEXT_RECOVERY_AT:
                    try:
                        recover_oled(hard=False)
                    except Exception:
                        _sleep_with_heartbeat(2)
                else:
                    _sleep_with_heartbeat(2)
            else:
                slider(lock)
                _sleep_with_heartbeat(misc.conf['slider'].get('time', 10.0))
            continue

        slider(lock)
        return

# --- main ---
if __name__ == '__main__':
    lock = mp.Lock()
    welcome()
    try:
        auto_slider(lock)
    finally:
        goodbye()
