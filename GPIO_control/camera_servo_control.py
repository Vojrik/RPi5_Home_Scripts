#!/usr/bin/env python3
import argparse
import ctypes
import errno
import glob
import os
import signal
import sys
import time

try:
    import lgpio
except ImportError:
    lgpio = None

PAN_GPIO = 24
TILT_GPIO = 25

DEFAULT_FREQ_HZ = 50
DEFAULT_MIN_US = 1000
DEFAULT_MAX_US = 2000
DEFAULT_HOLD_SECONDS = None


class ServoController:
    def __init__(self):
        self.handle = None
        self.active_pins = []

    def open(self):
        if self.handle is None:
            self.handle = lgpio.gpiochip_open(0)

    def start_servo(self, gpio, pulse_us, freq_hz, offset_us=0):
        self.open()
        lgpio.gpio_claim_output(self.handle, gpio)
        period_us = int(round(1_000_000 / float(freq_hz)))
        pulse_on = int(pulse_us)
        pulse_off = max(1, period_us - pulse_on)
        lgpio.tx_pulse(self.handle, gpio, pulse_on, pulse_off, int(offset_us), 0)
        self.active_pins.append(gpio)

    def stop_all(self):
        if self.handle is None:
            return
        for gpio in self.active_pins:
            lgpio.tx_pulse(self.handle, gpio, 0, 0, 0, 0)
            lgpio.gpio_free(self.handle, gpio)
        self.active_pins = []

    def close(self):
        if self.handle is not None:
            lgpio.gpiochip_close(self.handle)
            self.handle = None


class SysfsPwmController:
    def __init__(self, channels, freq_hz):
        self.channels = channels
        self.freq_hz = freq_hz
        self.period_ns = int(round(1_000_000_000 / float(freq_hz)))
        self.active = []

    def _write(self, path, value):
        with open(path, "w") as handle:
            handle.write(str(value))

    def _export_channel(self, chip_path, channel):
        pwm_path = os.path.join(chip_path, f"pwm{channel}")
        if not os.path.exists(pwm_path):
            self._write(os.path.join(chip_path, "export"), channel)
            for _ in range(50):
                if os.path.exists(pwm_path):
                    break
                time.sleep(0.01)
        return pwm_path

    def start_servo(self, channel_index, pulse_us):
        chip_path, channel = self.channels[channel_index]
        pwm_path = self._export_channel(chip_path, channel)
        try:
            self._write(os.path.join(pwm_path, "enable"), 0)
        except FileNotFoundError:
            pass
        self._write(os.path.join(pwm_path, "period"), self.period_ns)
        self._write(os.path.join(pwm_path, "duty_cycle"), int(pulse_us) * 1000)
        self._write(os.path.join(pwm_path, "enable"), 1)
        self.active.append((chip_path, channel))

    def update_servo(self, channel_index, pulse_us):
        chip_path, channel = self.channels[channel_index]
        pwm_path = os.path.join(chip_path, f"pwm{channel}")
        self._write(os.path.join(pwm_path, "duty_cycle"), int(pulse_us) * 1000)

    def stop_all(self):
        for chip_path, channel in self.active:
            pwm_path = os.path.join(chip_path, f"pwm{channel}")
            try:
                self._write(os.path.join(pwm_path, "duty_cycle"), 0)
                self._write(os.path.join(pwm_path, "enable"), 0)
            except FileNotFoundError:
                pass
        self.active = []


def clamp(value, low, high):
    return max(low, min(high, value))


def percent_to_pulse(percent, min_us, max_us):
    span = max_us - min_us
    scaled = (percent + 100.0) / 200.0
    return int(round(min_us + span * scaled))


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"Control pan/tilt servos for camera (GPIO{PAN_GPIO} pan, GPIO{TILT_GPIO} tilt).",
    )
    parser.add_argument("--pan", type=float, help="Pan position in range -100..100 (0=center).")
    parser.add_argument("--tilt", type=float, help="Tilt position in range -100..100 (0=center).")
    parser.add_argument("--freq-hz", type=int, default=DEFAULT_FREQ_HZ, help="PWM frequency in Hz.")
    parser.add_argument("--pan-min-us", type=int, default=DEFAULT_MIN_US, help="Pan min pulse width in us.")
    parser.add_argument("--pan-max-us", type=int, default=DEFAULT_MAX_US, help="Pan max pulse width in us.")
    parser.add_argument("--tilt-min-us", type=int, default=DEFAULT_MIN_US, help="Tilt min pulse width in us.")
    parser.add_argument("--tilt-max-us", type=int, default=DEFAULT_MAX_US, help="Tilt max pulse width in us.")
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=DEFAULT_HOLD_SECONDS,
        help="How long to hold PWM before stopping (ignored with --keep).",
    )
    parser.add_argument("--keep", action="store_true", help="Keep PWM running until interrupted.")
    parser.add_argument(
        "--pan-offset-us",
        type=int,
        default=0,
        help="Pulse offset in microseconds (lgpio backend only).",
    )
    parser.add_argument(
        "--tilt-offset-us",
        type=int,
        default=0,
        help="Pulse offset in microseconds (lgpio backend only).",
    )
    parser.add_argument(
        "--stagger",
        action="store_true",
        help="Stagger tilt pulse by half period when both pan and tilt are active (lgpio/bitbang only).",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "lgpio", "bitbang", "pwm-pio"),
        default="bitbang",
        help="PWM backend: pwm-pio (Pi 5 overlay), lgpio (userspace), bitbang (RT loop), or auto.",
    )
    parser.add_argument(
        "--rt",
        action="store_true",
        help="Attempt to enable real-time scheduling to reduce jitter (requires root).",
    )
    parser.add_argument(
        "--busy-wait-us",
        type=int,
        default=300,
        help="Busy-wait for the last N microseconds of each edge (bitbang only).",
    )
    parser.add_argument(
        "--max-late-us",
        type=int,
        default=600,
        help="Skip a PWM cycle if an edge is late by this many microseconds (bitbang only).",
    )
    parser.add_argument(
        "--pwmchip",
        default=None,
        help="PWM chip index or path to use for pwm-pio (e.g. 2 or /sys/class/pwm/pwmchip2).",
    )
    parser.add_argument(
        "--pan-channel",
        type=int,
        default=0,
        help="PWM channel index for pan (pwm-pio only).",
    )
    parser.add_argument(
        "--tilt-channel",
        type=int,
        default=1,
        help="PWM channel index for tilt (pwm-pio only).",
    )
    parser.add_argument(
        "--cpu",
        type=int,
        default=None,
        help="Pin process to a single CPU core (improves timing stability).",
    )
    return parser.parse_args()


def validate_limits(min_us, max_us, label):
    if min_us >= max_us:
        raise ValueError(f"{label} min must be less than max.")


def validate_percent(value, label):
    if value is None:
        return
    if value < -100 or value > 100:
        raise ValueError(f"{label} must be in range -100..100.")


def enable_realtime():
    if os.geteuid() != 0:
        print("Real-time scheduling requires root; continuing without --rt.")
        return
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(80))
    except PermissionError:
        print("Failed to set real-time scheduling; continuing without --rt.")
    except OSError as exc:
        print(f"Failed to set real-time scheduling: {exc}. Continuing without --rt.")


def resolve_backend(requested):
    if requested == "pwm-pio":
        return "pwm-pio"
    if requested == "lgpio":
        if lgpio is None:
            raise RuntimeError("Missing python3-rpi-lgpio. Install with: sudo apt install python3-rpi-lgpio")
        return "lgpio"
    if requested == "bitbang":
        if lgpio is None:
            raise RuntimeError("Missing python3-rpi-lgpio. Install with: sudo apt install python3-rpi-lgpio")
        return "bitbang"
    if pwm_pio_available():
        return "pwm-pio"
    if lgpio is not None:
        return "lgpio"
    raise RuntimeError("Missing python3-rpi-lgpio. Install with: sudo apt install python3-rpi-lgpio")

_STOP_REQUESTED = False


def handle_exit_flag(_signum, _frame):
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


_LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
_CLOCK_MONOTONIC = 1
_TIMER_ABSTIME = 1


def sleep_until_ns(target_ns):
    ts = _Timespec(target_ns // 1_000_000_000, target_ns % 1_000_000_000)
    while True:
        res = _LIBC.clock_nanosleep(_CLOCK_MONOTONIC, _TIMER_ABSTIME, ctypes.byref(ts), None)
        if res == 0:
            return
        if res == errno.EINTR:
            continue
        raise OSError(res, "clock_nanosleep failed")


def sleep_until_ns_with_busy_wait(target_ns, busy_wait_ns):
    if busy_wait_ns <= 0:
        sleep_until_ns(target_ns)
        return
    while True:
        now_ns = time.monotonic_ns()
        remaining_ns = target_ns - now_ns
        if remaining_ns <= 0:
            return
        if remaining_ns > busy_wait_ns:
            sleep_until_ns(target_ns - busy_wait_ns)
            continue
        while time.monotonic_ns() < target_ns:
            pass
        return


def set_affinity(cpu):
    if cpu is None:
        return
    try:
        os.sched_setaffinity(0, {cpu})
    except (AttributeError, PermissionError, OSError) as exc:
        print(f"Failed to set CPU affinity: {exc}. Continuing without affinity pinning.")


def _read_compat(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return ""
    return "\n".join([part for part in raw.decode("ascii", "ignore").split("\x00") if part])


def _read_text(path):
    try:
        with open(path, "r", encoding="ascii") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def pwm_pio_available():
    return bool(find_pwm_pio_chips())


def find_pwm_pio_chips():
    chips = sorted(glob.glob("/sys/class/pwm/pwmchip*"))
    pwm_pio = []
    for chip in chips:
        compat = _read_compat(os.path.join(chip, "device", "of_node", "compatible"))
        name = _read_text(os.path.join(chip, "device", "of_node", "name"))
        if "pwm-pio" in compat or "pio-pwm" in compat or "pwm-pio" in name:
            pwm_pio.append(chip)
    if pwm_pio:
        return pwm_pio
    for chip in chips:
        compat = _read_compat(os.path.join(chip, "device", "of_node", "compatible"))
        if compat and "rp1-pwm" not in compat:
            pwm_pio.append(chip)
    return pwm_pio


def pwmchip_from_arg(value):
    if value is None:
        return None
    if str(value).isdigit():
        return f"/sys/class/pwm/pwmchip{value}"
    return value


def allocate_pwm_channels(chips, needed):
    channels = []
    for chip in chips:
        try:
            npwm = int(_read_text(os.path.join(chip, "npwm")) or "0")
        except ValueError:
            npwm = 0
        for channel in range(npwm):
            channels.append((chip, channel))
    if len(channels) < needed:
        raise RuntimeError(
            f"Not enough pwm-pio channels for {needed} servo(s)."
        )
    return channels[:needed]


def run_bitbang(
    pan_us,
    tilt_us,
    pan_offset_us,
    tilt_offset_us,
    freq_hz,
    busy_wait_us,
    max_late_us,
    hold_seconds,
    keep,
    pan_active,
    tilt_active,
):
    if not pan_active and not tilt_active:
        return 0

    handle = lgpio.gpiochip_open(0)
    try:
        if pan_active:
            lgpio.gpio_claim_output(handle, PAN_GPIO)
        if tilt_active:
            lgpio.gpio_claim_output(handle, TILT_GPIO)

        period_ns = int(round(1_000_000_000 / float(freq_hz)))
        busy_wait_ns = int(max(0, busy_wait_us) * 1000)
        max_late_ns = int(max(0, max_late_us) * 1000)
        pan_offset_ns = int(pan_offset_us * 1000)
        tilt_offset_ns = int(tilt_offset_us * 1000)
        pan_pulse_ns = int(pan_us * 1000) if pan_active else 0
        tilt_pulse_ns = int(tilt_us * 1000) if tilt_active else 0

        start_ns = time.monotonic_ns()
        end_ns = None if keep or hold_seconds is None else start_ns + int(hold_seconds * 1_000_000_000)
        cycle_start = start_ns

        while not _STOP_REQUESTED and (end_ns is None or time.monotonic_ns() < end_ns):
            events = []
            if pan_active:
                events.append((cycle_start + pan_offset_ns, PAN_GPIO, 1))
                events.append((cycle_start + pan_offset_ns + pan_pulse_ns, PAN_GPIO, 0))
            if tilt_active:
                events.append((cycle_start + tilt_offset_ns, TILT_GPIO, 1))
                events.append((cycle_start + tilt_offset_ns + tilt_pulse_ns, TILT_GPIO, 0))

            events.sort(key=lambda item: item[0])
            missed_deadline = False
            for ts_ns, gpio, level in events:
                now_ns = time.monotonic_ns()
                if max_late_ns and now_ns > ts_ns + max_late_ns:
                    missed_deadline = True
                    break
                sleep_until_ns_with_busy_wait(ts_ns, busy_wait_ns)
                lgpio.gpio_write(handle, gpio, level)

            if missed_deadline:
                if pan_active:
                    lgpio.gpio_write(handle, PAN_GPIO, 0)
                if tilt_active:
                    lgpio.gpio_write(handle, TILT_GPIO, 0)
                cycle_start = time.monotonic_ns() + period_ns
                continue

            next_cycle = cycle_start + period_ns
            sleep_until_ns_with_busy_wait(next_cycle, busy_wait_ns)
            cycle_start = next_cycle
    finally:
        if pan_active:
            lgpio.gpio_write(handle, PAN_GPIO, 0)
            lgpio.gpio_free(handle, PAN_GPIO)
        if tilt_active:
            lgpio.gpio_write(handle, TILT_GPIO, 0)
            lgpio.gpio_free(handle, TILT_GPIO)
        lgpio.gpiochip_close(handle)
    return 0


def main():
    args = parse_args()

    if args.pan is None and args.tilt is None:
        print("Specify at least one of --pan or --tilt.")
        return 2

    try:
        validate_limits(args.pan_min_us, args.pan_max_us, "Pan")
        validate_limits(args.tilt_min_us, args.tilt_max_us, "Tilt")
        validate_percent(args.pan, "Pan")
        validate_percent(args.tilt, "Tilt")
    except ValueError as exc:
        print(str(exc))
        return 2

    if args.rt:
        enable_realtime()
    set_affinity(args.cpu)

    try:
        backend = resolve_backend(args.backend)
    except RuntimeError as exc:
        print(str(exc))
        return 2

    controller = ServoController()
    pwm_pio_controller = None
    pwm_channel_map = {}
    if backend == "pwm-pio":
        active_servos = []
        if args.pan is not None:
            active_servos.append("pan")
        if args.tilt is not None:
            active_servos.append("tilt")
        if not active_servos:
            print("Specify at least one of --pan or --tilt.")
            return 2
        chip_override = pwmchip_from_arg(args.pwmchip)
        if chip_override:
            channels = []
            if args.pan is not None:
                channels.append((chip_override, args.pan_channel))
            if args.tilt is not None:
                channels.append((chip_override, args.tilt_channel))
        else:
            chips = find_pwm_pio_chips()
            if not chips:
                print(
                    "pwm-pio device not found. Add dtoverlay=pwm-pio,gpio=24/25 to "
                    "/boot/firmware/config.txt and reboot."
                )
                return 2
            channels = allocate_pwm_channels(chips, len(active_servos))
        pwm_pio_controller = SysfsPwmController(channels, args.freq_hz)
        for index, servo_name in enumerate(active_servos):
            pwm_channel_map[servo_name] = index

    def handle_exit(_signum, _frame):
        if backend == "bitbang":
            handle_exit_flag(_signum, _frame)
            return
        if backend == "pwm-pio" and pwm_pio_controller is not None:
            pwm_pio_controller.stop_all()
        else:
            controller.stop_all()
            controller.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    period_us = int(round(1_000_000 / float(args.freq_hz)))
    pan_offset = args.pan_offset_us
    tilt_offset = args.tilt_offset_us
    if args.stagger and args.pan is not None and args.tilt is not None:
        tilt_offset = period_us // 2

    pan_us = 0
    tilt_us = 0
    if args.pan is not None:
        pan_percent = clamp(args.pan, -100, 100)
        pan_us = percent_to_pulse(pan_percent, args.pan_min_us, args.pan_max_us)
        if backend == "pwm-pio":
            pwm_pio_controller.start_servo(pwm_channel_map["pan"], pan_us)
            print(f"Pan GPIO{PAN_GPIO}: {pan_percent:.1f}% -> {pan_us} us @ {args.freq_hz} Hz")
        elif backend != "bitbang":
            controller.start_servo(PAN_GPIO, pan_us, args.freq_hz, pan_offset)
            print(
                f"Pan GPIO{PAN_GPIO}: {pan_percent:.1f}% -> {pan_us} us @ {args.freq_hz} Hz"
                f" (offset {pan_offset} us)"
            )

    if args.tilt is not None:
        tilt_percent = clamp(args.tilt, -100, 100)
        tilt_us = percent_to_pulse(tilt_percent, args.tilt_min_us, args.tilt_max_us)
        if backend == "pwm-pio":
            pwm_pio_controller.start_servo(pwm_channel_map["tilt"], tilt_us)
            print(f"Tilt GPIO{TILT_GPIO}: {tilt_percent:.1f}% -> {tilt_us} us @ {args.freq_hz} Hz")
        elif backend != "bitbang":
            controller.start_servo(TILT_GPIO, tilt_us, args.freq_hz, tilt_offset)
            print(
                f"Tilt GPIO{TILT_GPIO}: {tilt_percent:.1f}% -> {tilt_us} us @ {args.freq_hz} Hz"
                f" (offset {tilt_offset} us)"
            )

    if backend == "bitbang":
        print("Using bitbang backend. PWM timing is driven by a real-time loop.")
        if args.busy_wait_us > 0:
            print(f"Busy-wait enabled for last {args.busy_wait_us} us of each edge.")
        if args.max_late_us > 0:
            print(f"Skipping PWM cycle if an edge is late by {args.max_late_us} us.")
        if args.pan is not None:
            print(
                f"Pan GPIO{PAN_GPIO}: {pan_percent:.1f}% -> {pan_us} us @ {args.freq_hz} Hz"
                f" (offset {pan_offset} us)"
            )
        if args.tilt is not None:
            print(
                f"Tilt GPIO{TILT_GPIO}: {tilt_percent:.1f}% -> {tilt_us} us @ {args.freq_hz} Hz"
                f" (offset {tilt_offset} us)"
            )
        return run_bitbang(
            pan_us if args.pan is not None else 0,
            tilt_us if args.tilt is not None else 0,
            pan_offset,
            tilt_offset,
            args.freq_hz,
            args.busy_wait_us,
            args.max_late_us,
            args.hold_seconds,
            args.keep or args.hold_seconds is None,
            args.pan is not None,
            args.tilt is not None,
        )

    if args.keep or args.hold_seconds is None:
        print("PWM running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)

    time.sleep(max(0.0, args.hold_seconds))
    if backend == "pwm-pio" and pwm_pio_controller is not None:
        pwm_pio_controller.stop_all()
    else:
        controller.stop_all()
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
