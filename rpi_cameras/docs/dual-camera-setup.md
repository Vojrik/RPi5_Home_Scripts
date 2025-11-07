# Dual camera configuration (Raspberry Pi 5)

These notes capture the configuration tested for enabling two Raspberry Pi camera modules with `camera-streamer` and WebRTC endpoints on ports 8081 and 8082.

## Prerequisites

1. Install build dependencies from the upstream project (`sudo apt install meson ninja-build libcamera-dev libevent-dev libssl-dev`).
2. Build and deploy the streamer:
   ```bash
   meson setup build
   ninja -C build
   sudo ninja -C build install
   ```
3. Verify both sensors are detected:
   ```bash
   libcamera-still --list-cameras
   ```
   Record the reported `/base/...` paths for CAM0 and CAM1 and update `systemd/camera-streamer.env` accordingly.

## Provisioning services

Run the helper to install the environment file and systemd units:
```bash
scripts/deploy-camera-streamer.sh
```
The script reloads systemd and enables both units. TURN credentials remain outside the repo; populate `/etc/camera-streamer/camera-streamer.secrets` when required.

### Soft MJPEG konfigurace

Pro softwarový MJPEG portál (`camera-soft-cam{0,1}.service`) se nastavení čte z `/etc/camera-streamer/camera-soft-stream.env`. Šablona je verzovaná jako `systemd/camera-soft-stream.env`; po úpravách ji nasadíš:
```bash
sudo install -m 640 systemd/camera-soft-stream.env /etc/camera-streamer/camera-soft-stream.env
sudo systemctl restart camera-soft-cam0.service camera-soft-cam1.service
```

## Validation

- Confirm HTTP endpoints: `curl http://<pi>:8081/status` and `curl http://<pi>:8082/status`.
- Open WebRTC: navigate to `http://<pi>:8081/webrtc` or `:8082/webrtc`; confirm playback.
- Run the port smoke test from this repo:
  ```bash
  tests/webrtc/ports_test.sh
  ```
- For detailed media stats use `chrome://webrtc-internals` while the stream is active.

## Troubleshooting

- If `systemctl status camera-streamer-cam0` reports sensor errors, double-check the `cam*_path` in the env file matches `libcamera-still` output.
- ICE connectivity issues usually stem from missing TURN credentials; update `webrtc_ice_servers` and restart the units (`sudo systemctl restart camera-streamer-cam{0,1}`).
- When switching resolutions, refresh the SDP templates under `webrtc/sdp/` for traceability.
