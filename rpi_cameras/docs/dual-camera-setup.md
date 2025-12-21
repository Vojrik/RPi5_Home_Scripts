# Dual Camera Configuration (Raspberry Pi 5)

These notes describe the current software MJPEG portal built on top of `soft-stream.py`. The service runs on a Raspberry Pi 5, serves two CSI cameras, and exposes OctoPrint/facility previews via nginx on ports 8081 (CAM0) and 8082 (CAM1) while the internal services listen on 18081/18082.

## Requirements

1. Install the Picamera2 stack from Raspberry Pi OS (the `python3-picamera2` package pulls in `libcamera`).  
2. Confirm both sensors are visible:
   ```bash
   libcamera-still --list-cameras
   ```
   The order of the list determines `cam0_index` / `cam1_index` in the environment file.
3. Ensure `/home/vojrik/Scripts/rpi_cameras` (this repository) and `/etc/camera-streamer/` (host-specific config) exist on the target Pi.

## Deployment / Updates

1. Edit `systemd/camera-soft-stream.env` to set resolution, FPS, quality, autofocus, and snapshot parameters.
2. From the repo root run:
   ```bash
   cd ~/Scripts/rpi_cameras
   ./deploy-soft-stream.sh
   ```
   The helper copies `soft-stream.py`, `measure_fps.py`, and `README.md` into the runtime directory, refreshes `/etc/camera-streamer/camera-soft-stream.env`, installs `camera-soft-cam{0,1}.service`, and finishes with `systemctl daemon-reload && enable --now`.
3. Verify both services are active:
   ```bash
   systemctl status camera-soft-cam0.service
   systemctl status camera-soft-cam1.service
   ```

## Operational Validation

- Visit `http://<pi>:8081/` (CAM0) and `http://<pi>:8082/` (CAM1) through nginx; the landing page links to `stream.mjpg` and `snapshot.jpg`.  
- `curl http://<pi>:8081/stream.mjpg --output /dev/null` should start receiving multipart MJPEG data almost immediately (nginx auth applies).  
- To measure FPS, use the bundled tool:
  ```bash
  python3 /home/vojrik/Scripts/rpi_cameras/measure_fps.py http://127.0.0.1:18082/stream.mjpg --frames 150
  ```
- Track autofocus events and camera availability via `journalctl -u camera-soft-camX.service -n 50`.

## Environment File Layout

`systemd/camera-soft-stream.env` provides separate `cam0_*` and `cam1_*` sections:

- `camX_index` – index reported by `Picamera2.global_camera_info()`.
- `camX_width`, `camX_height`, `camX_fps` – stream parameters; the script logs the negotiated resolution when hardware tweaks it.
- `camX_port` – internal HTTP port (defaults: 18081 / 18082).  
- `camX_snapshot_*` – still capture resolution/quality used when no stream is running.  
- `camX_autofocus` – enables `autofocus_cycle()` before stream start and before snapshots.

After editing the file, restart both services:
```bash
sudo systemctl restart camera-soft-cam0.service camera-soft-cam1.service
```

## Troubleshooting

- **Missing camera** – when a sensor is absent, the server exits with code 66 and the unit stays `inactive (dead)`. Reconnect the ribbon cable and run `sudo systemctl restart camera-soft-camX.service`.  
- **Autofocus timeouts** – check logs; if the lens keeps failing, set `camX_autofocus=0` and adjust focus manually.  
- **Unexpected resolution** – Picamera2 logs when the ISP enforces a different size. Update `camX_width`/`height` to a supported value.  
- **Port collision** – adjust `camX_port` in the env file and rerun the deploy script so unit files are updated as well.

## Legacy Note

The original `camera-streamer` + WebRTC build is no longer used on the Pi 5 (no HW H.264). Those files live only as historical references in `/home/vojrik/camera-streamer`. The current repository focuses solely on the soft-MJPEG workflow described above.
