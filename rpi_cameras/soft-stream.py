#!/usr/bin/env python3
import argparse
import io
import logging
import sys
import tempfile
import threading
from http import HTTPStatus, server
from typing import Optional

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.encoders.encoder import Quality
from picamera2.outputs import FileOutput

from libcamera import controls


PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{name} - Camera Portal</title>
    <style>
      body {{
        font-family: sans-serif;
        margin: 0;
        background: #1e1e1e;
        color: #f0f0f0;
      }}
      header {{
        background: #3c3c3c;
        padding: 1.5rem 2rem;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
      }}
      main {{
        padding: 2rem;
        max-width: 960px;
        margin: 0 auto;
      }}
      h1 {{
        margin: 0;
        font-size: 1.8rem;
      }}
      .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 1.5rem;
        margin-top: 2rem;
      }}
      .card {{
        background: #2b2b2b;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.25);
      }}
      .card h2 {{
        margin-top: 0;
        font-size: 1.2rem;
      }}
      .card a {{
        color: #61dafb;
        text-decoration: none;
        font-weight: bold;
      }}
      .details {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 1rem;
        margin-top: 1.5rem;
      }}
      .badge {{
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        background: #444;
        margin-right: 0.5rem;
      }}
      footer {{
        margin-top: 3rem;
        font-size: 0.85rem;
        color: #c0c0c0;
      }}
      code {{
        background: #111;
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
      }}
    </style>
  </head>
  <body>
    <header>
      <h1>{name} – Camera Portal</h1>
      <p>Softwarový MJPEG – stream se spouští jen při otevřené stránce. Když okno zavřeš, kamera se odpojí a zátěž CPU spadne.</p>
    </header>
    <main>
      <section class="details">
        <div><span class="badge">Rozlišení</span>{width}×{height}</div>
        <div><span class="badge">Snímková frekvence</span>{fps} fps</div>
        <div><span class="badge">Kvalita</span>{quality}</div>
        <div><span class="badge">Port</span>{port}</div>
      </section>
      <section class="cards">
        <article class="card">
          <h2>MJPEG</h2>
          <p>Živý stream běžící jen při otevřeném klientovi.</p>
          <p><a href="stream.mjpg">stream.mjpg</a></p>
        </article>
        <article class="card">
          <h2>Snapshot</h2>
          <p>Jednorázový snímek JPG – při neaktivním streamu se pořídí plné rozlišení {snap_width}×{snap_height} (quality {snap_quality}).</p>
          <p><a href="snapshot.jpg">snapshot.jpg</a></p>
        </article>
        <article class="card">
          <h2>WebRTC</h2>
          <p>RP1 nemá HW H.264/MJPEG enkodér. WebRTC profil camera-streameru proto na Pi 5 nejede.</p>
          <p><a href="webrtc">více informací</a></p>
        </article>
        <article class="card">
          <h2>Konfigurace</h2>
          <p>Uprav soubor <code>/etc/camera-streamer/camera-soft-stream.env</code> a udělej restart služby:</p>
          <p><code>sudo systemctl restart camera-soft-cam0.service</code></p>
        </article>
      </section>
      <footer>
        <p>Trvalé softwarové řešení – parametry (rozlišení, FPS, kvalita) lze měnit v env souboru a následně restartovat služby.</p>
      </footer>
    </main>
  </body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame: Optional[bytes] = None
        self.buffer = io.BytesIO()
        self.condition = threading.Condition()

    def write(self, buf):
        if buf.startswith(b"\xff\xd8"):
            self.buffer.seek(0)
            self.buffer.truncate()
        self.buffer.write(buf)
        if buf.endswith(b"\xff\xd9"):
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
            self.buffer.truncate()
        return len(buf)

    def writable(self):
        return True

    def wait_for_frame(self, timeout=None):
        with self.condition:
            notified = self.condition.wait(timeout)
            if not notified:
                return None
            return self.frame

    def reset(self):
        with self.condition:
            self.buffer = io.BytesIO()
            self.frame = None
            self.condition.notify_all()


class CameraManager:
    def __init__(self, index, width, height, framerate, quality, name, snapshot_width=None, snapshot_height=None, snapshot_quality=95, autofocus=False, camera_id=None):
        self.index = index
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.framerate = framerate
        self.quality = quality
        self.name = name
        self.snapshot_width = snapshot_width or width
        self.snapshot_height = snapshot_height or height
        self.snapshot_quality = snapshot_quality
        self.autofocus = autofocus

        self.output = StreamingOutput()
        self._lock = threading.Lock()
        self._picam2: Optional[Picamera2] = None
        self._video_config = None
        self._streaming = False
        self._clients = 0

    def _ensure_camera(self):
        if self._picam2 is None:
            stream_size = (self.width, self.height)
            self._picam2 = Picamera2(self.index)
            self._video_config = self._picam2.create_video_configuration(
                main={"size": stream_size},
                controls={"FrameDurationLimits": (int(1_000_000 / self.framerate), int(1_000_000 / self.framerate))}
            )

    def _enable_autofocus(self, mode=None):
        if not self.autofocus or self._picam2 is None:
            return
        if mode is None:
            mode = controls.AfModeEnum.Continuous
        request = {"AfMode": mode}
        try:
            if hasattr(controls, "AfRangeEnum"):
                request["AfRange"] = controls.AfRangeEnum.Full
            if hasattr(controls, "AfSpeedEnum"):
                request["AfSpeed"] = controls.AfSpeedEnum.Normal
            self._picam2.set_controls(request)
        except Exception as exc:
            logging.warning("Failed to set autofocus controls for %s: %s", self.name, exc)

    def _run_autofocus_cycle(self, wait: float = 1.5, resume_continuous: bool = False):
        if not self.autofocus or self._picam2 is None:
            return
        try:
            result = self._picam2.autofocus_cycle(wait=wait)
        except AttributeError:
            logging.debug("Autofocus cycle not supported on this platform for %s", self.name)
            return
        except Exception as exc:
            logging.warning("Autofocus cycle for %s failed: %s", self.name, exc)
            return
        if result is False:
            logging.warning("Autofocus cycle for %s timed out (wait %.1fs)", self.name, wait)
            return
        logging.info("Autofocus cycle for %s completed successfully", self.name)
        if resume_continuous:
            try:
                resume_request = {"AfMode": controls.AfModeEnum.Continuous}
                if hasattr(controls, "AfRangeEnum"):
                    resume_request["AfRange"] = controls.AfRangeEnum.Full
                if hasattr(controls, "AfSpeedEnum"):
                    resume_request["AfSpeed"] = controls.AfSpeedEnum.Normal
                self._picam2.set_controls(resume_request)
            except Exception as exc:
                logging.warning("Failed to switch %s back to continuous autofocus: %s", self.name, exc)

    def start_stream(self):
        with self._lock:
            self._clients += 1
            if not self._streaming:
                logging.info("Starting stream for %s", self.name)
                self._ensure_camera()
                try:
                    self._picam2.stop()
                except Exception:
                    pass
                self._picam2.configure(self._video_config)
                actual_size = tuple(self._picam2.camera_configuration()['main']['size'])
                if actual_size != (self.width, self.height):
                    logging.warning('Kamera %s upravila rozlišení na %dx%d (požadováno %dx%d)', self.name, actual_size[0], actual_size[1], self.width, self.height)
                else:
                    logging.info('Kamera %s běží na požadovaném rozlišení %dx%d', self.name, actual_size[0], actual_size[1])
                self._picam2.start()
                self._enable_autofocus(mode=controls.AfModeEnum.Continuous)
                self._run_autofocus_cycle(wait=3.0, resume_continuous=True)
                self._picam2.start_recording(MJPEGEncoder(), FileOutput(self.output), quality=self.quality)
                self._streaming = True

    def stop_stream(self):
        with self._lock:
            if self._clients > 0:
                self._clients -= 1
            if self._clients == 0 and self._streaming:
                logging.info("Stopping stream for %s", self.name)
                self._picam2.stop_recording()
                self._picam2.stop()
                self._picam2.close()
                self._picam2 = None
                self._video_config = None
                self._streaming = False
                self.output.reset()

    def snapshot(self, timeout=2.0):
        if self._streaming:
            frame = self.output.wait_for_frame(timeout)
            if frame is None:
                raise RuntimeError("Snapshot timeout")
            return frame

        with self._lock:
            logging.info("Capturing single frame for %s", self.name)
            self._ensure_camera()
            still_size = (self.snapshot_width or self.width, self.snapshot_height or self.height)
            still_config = self._picam2.create_still_configuration(main={"size": still_size})
            try:
                self._picam2.stop()
            except Exception:
                pass
            self._picam2.configure(still_config)
            self._picam2.start()
            self._enable_autofocus(mode=controls.AfModeEnum.Auto)
            self._run_autofocus_cycle(wait=2.0, resume_continuous=False)
            buffer = io.BytesIO()
            self._picam2.capture_file(buffer, format="jpeg")
            self._picam2.stop()
            self._picam2.close()
            self._picam2 = None
            self._video_config = None
            return buffer.getvalue()


    @property
    def streaming(self):
        with self._lock:
            return self._streaming


QUALITY_MAP = {
    "very-low": Quality.VERY_LOW,
    "low": Quality.LOW,
    "medium": Quality.MEDIUM,
    "high": Quality.HIGH,
    "very-high": Quality.VERY_HIGH,
}



EXIT_NO_CAMERA = 66


def resolve_camera_index(camera_id: Optional[str], fallback_index: int) -> Optional[int]:
    try:
        infos = Picamera2.global_camera_info()
    except Exception as exc:
        logging.error("Nedokážu načíst seznam kamer: %s", exc)
        return None

    if camera_id:
        for idx, info in enumerate(infos or []):
            if isinstance(info, dict) and info.get("Id") == camera_id:
                logging.info("Kamera s ID %s nalezena na indexu %d.", camera_id, idx)
                return idx
        logging.warning("Kamera s ID %s nebyla nalezena.", camera_id)
        return None

    return fallback_index


def probe_camera(index: int, camera_id: Optional[str] = None) -> bool:
    try:
        infos = Picamera2.global_camera_info()
    except Exception as exc:
        logging.error("Nedokážu načíst seznam kamer: %s", exc)
        return False

    if index < 0:
        return False

    if not infos or index >= len(infos):
        logging.warning("Požadovaná kamera s indexem %d nebyla nalezena.", index)
        return False

    info = infos[index] or {}
    if isinstance(info, dict) and info.get('Unavailable'):
        logging.warning("Kamera s indexem %d je označena jako nedostupná.", index)
        return False

    try:
        probe = Picamera2(index)
    except Exception as exc:
        logging.warning("Inicializace kamery s indexem %d selhala: %s", index, exc)
        return False

    try:
        probe.close()
    except Exception:
        pass
    return True


def serve(manager: CameraManager, port: int, bind_host: str):
    class StreamingHandler(server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                snap_w = manager.snapshot_width or manager.width
                snap_h = manager.snapshot_height or manager.height
                content = PAGE_TEMPLATE.format(
                    name=manager.name,
                    width=manager.width,
                    height=manager.height,
                    fps=manager.framerate,
                    quality=manager.quality.name.replace("_", " ").title(),
                    port=port,
                    snap_width=snap_w,
                    snap_height=snap_h,
                    snap_quality=manager.snapshot_quality,
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            if self.path == "/stream.mjpg":
                manager.start_stream()
                self.send_response(HTTPStatus.OK)
                self.send_header("Age", "0")
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
                self.end_headers()
                try:
                    while True:
                        frame = manager.output.wait_for_frame(timeout=5)
                        if not frame:
                            continue
                        self.wfile.write(b"--FRAME\r\n")
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                except BrokenPipeError:
                    logging.info("Client %s disconnected from %s stream", self.client_address, manager.name)
                except Exception as exc:  # pragma: no cover
                    logging.warning("Removed streaming client %s: %s", self.client_address, exc)
                finally:
                    manager.stop_stream()
                return

            if self.path == "/snapshot.jpg":
                try:
                    data = manager.snapshot()
                except RuntimeError as exc:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if self.path == "/webrtc":
                message = (
                    "<html><head><title>WebRTC nedostupné</title></head>"
                    "<body><h1>WebRTC není podporováno</h1>"
                    "<p>RP1 čip Raspberry Pi 5 nemá zabudovaný hardwarový H.264/MJPEG enkodér, "
                    "takže původní WebRTC pipeline camera-streameru nemůže běžet.</p>"
                    "<p>Aktuální instance poskytuje pouze softwarový MJPEG stream.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_HEAD(self):
            if self.path in ("/", "/stream.mjpg", "/snapshot.jpg", "/webrtc"):
                self.send_response(HTTPStatus.OK)
                self.end_headers()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format, *args):
            logging.info("%s - %s", self.address_string(), format % args)

    address = (bind_host, port)
    httpd = server.ThreadingHTTPServer(address, StreamingHandler)
    logging.info("Serving %s on http://%s:%d", manager.name, address[0], port)
    try:
        httpd.serve_forever()
    finally:
        manager.stop_stream()


def main():
    parser = argparse.ArgumentParser(description="Software MJPEG streaming portal for Picamera2.")
    parser.add_argument("--camera-index", type=int, default=0, help="Index kamery (default 0)")
    parser.add_argument("--camera-id", type=str, default=None, help="Persistentní ID kamery z Picamera2.global_camera_info()")
    parser.add_argument("--width", type=int, default=1280, help="Šířka obrazu")
    parser.add_argument("--height", type=int, default=720, help="Výška obrazu")
    parser.add_argument("--framerate", type=int, default=15, help="Snímková frekvence")
    parser.add_argument("--port", type=int, required=True, help="HTTP port")
    parser.add_argument("--bind", type=str, default="0.0.0.0", help="Bind address (default 0.0.0.0)")
    parser.add_argument(
        "--quality",
        type=str,
        default="medium",
        choices=list(QUALITY_MAP.keys()),
        help="Profil kvality MJPEG"
    )
    parser.add_argument("--name", type=str, default="Camera", help="Popisek kamery")
    parser.add_argument("--snapshot-width", type=int, default=0, help="Šířka snapshotu (0 = stejné jako stream)")
    parser.add_argument("--snapshot-height", type=int, default=0, help="Výška snapshotu (0 = stejné jako stream)")
    parser.add_argument("--snapshot-quality", type=int, default=95, help="JPEG kvalita snapshotu (1-100)")
    parser.add_argument("--autofocus", type=int, choices=[0, 1], default=0, help="Povolit kontinuální autofocus (1 = ano)")
    args = parser.parse_args()

    if not 1 <= args.snapshot_quality <= 100:
        parser.error("Snapshot kvalita musí být v rozsahu 1-100.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    effective_index = resolve_camera_index(args.camera_id, args.camera_index)
    if effective_index is None or not probe_camera(effective_index, args.camera_id):
        if args.camera_id:
            logging.error("Kamera s ID %s není dostupná. Spusť službu až po připojení požadované kamery.", args.camera_id)
        else:
            logging.error("Kamera s indexem %d není dostupná. Spusť službu až po připojení kamery.", args.camera_index)
        sys.exit(EXIT_NO_CAMERA)

    manager = CameraManager(
        index=effective_index,
        width=args.width,
        height=args.height,
        framerate=args.framerate,
        quality=QUALITY_MAP[args.quality],
        name=args.name,
        snapshot_width=args.snapshot_width or None,
        snapshot_height=args.snapshot_height or None,
        snapshot_quality=args.snapshot_quality,
        autofocus=bool(args.autofocus),
        camera_id=args.camera_id,
    )
    serve(manager, args.port, args.bind)


if __name__ == "__main__":
    main()
