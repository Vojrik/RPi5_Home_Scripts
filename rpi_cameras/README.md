# Raspberry Pi Soft Stream Cameras

This directory contains the lightweight MJPEG portal used for the two CSI cameras on the Raspberry Pi 5.  The code lives in `/home/vojrik/Scripts/rpi_cameras` on the target host and is managed by the `camera-soft-cam{0,1}.service` systemd units.

## Contents
- `soft-stream.py` – HTTP portal serving the landing page, `/stream.mjpg`, `/snapshot.jpg` and a WebRTC notice. It lazily opens the requested camera, keeps the feed running only while clients are connected and handles autofocus cycles before streaming and before out-of-band snapshots.
- `measure_fps.py` – simple MJPEG FPS probe (`python3 measure_fps.py http://127.0.0.1:18081/stream.mjpg`).
- `systemd/` – unit files and environment template (`camera-soft-stream.env`). Units are bound to `/dev/video*` and honour exit code `66` when a camera is missing.
- `deploy-soft-stream.sh` – helper invoked from the repository root to copy scripts, refresh `/etc/camera-streamer/*.env` files and restart the services.

## Deployment / Updates
1. Adjust `systemd/camera-soft-stream.env` in the repository (resolution, FPS, quality, autofocus, snapshot sizes).
   - For stable camera mapping, use `cam*_id` with the value from `Picamera2.global_camera_info()` - the service will always select the correct device even if `/dev/video*` indices shift.
2. Deploy to the Pi:
   ```bash
   ./Scripts/rpi_cameras/deploy-soft-stream.sh
   ```
3. After the script finishes, the services run from `/home/vojrik/Scripts/rpi_cameras` and load `/etc/camera-streamer/camera-soft-stream.env`.

## Runtime Behaviour
- **Camera presence check** – the Python server verifies the requested index via `Picamera2.global_camera_info()`. Missing cameras log an error and exit with code `66`, which systemd treats as a permanent stop until the hardware returns.
- **Device bindings** – `camera-soft-cam0.service` binds to `dev-video0.device`, `camera-soft-cam1.service` to `dev-video1.device`. Hotplugging a CSI cable is still discouraged; reconnecting requires `sudo systemctl restart camera-soft-camX.service`.
- **Autofocus** – when `camX_autofocus=1` the script:
  1. switches the camera to continuous AF on stream start and runs a blocking `autofocus_cycle()`;
  2. runs the same cycle before offline snapshots (using `AfMode=Auto` for single acquisition);
  3. logs any timeouts or failures to `journalctl -u camera-soft-camX.service`.
- **Stream watchdog** – while a client is connected, the server restarts the stream if no frames arrive for 10 seconds. Adjust via `--watchdog-timeout` (0 disables the watchdog).
- **Resolution logging** – after configuring the stream the script logs the actual negotiated `main` size so mismatches with the requested resolution are obvious.

## Operating the Services
```bash
# restart both after config changes
sudo systemctl restart camera-soft-cam0.service camera-soft-cam1.service

# start/stop individually
sudo systemctl start camera-soft-cam0.service
sudo systemctl stop camera-soft-cam1.service

# disable a camera that is physically unplugged
sudo systemctl disable --now camera-soft-cam0.service
```

### Checking Status & Logs
```bash
systemctl status camera-soft-cam0.service
journalctl -u camera-soft-cam1.service -n 50
```
Look for autofocus messages (`Autofocus cycle …`) and resolution logs to confirm expected behaviour.

## Measuring Stream Performance
```bash
python3 /home/vojrik/Scripts/rpi_cameras/measure_fps.py \
  http://127.0.0.1:18082/stream.mjpg --frames 150
```
Swap the port to `18081` for CAM0. The utility counts multipart frame boundaries and prints the observed FPS.

## Snapshot Usage
- External (via nginx auth): `http://<pi>:808X/stream.mjpg`, `http://<pi>:808X/snapshot.jpg`, `http://<pi>:808X/`.
- Internal (loopback only): `http://127.0.0.1:1808X/stream.mjpg`, `http://127.0.0.1:1808X/snapshot.jpg`, `http://127.0.0.1:1808X/`.

## Filesystem Layout Summary
```
/home/vojrik/Scripts/rpi_cameras/      # runtime copy of the scripts
/etc/camera-streamer/camera-soft-stream.env  # per-host configuration
/etc/systemd/system/camera-soft-cam*.service # installed units
```
