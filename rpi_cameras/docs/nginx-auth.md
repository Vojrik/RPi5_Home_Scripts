# Nginx auth for OctoPrint + MJPEG cameras

This setup keeps the external ports unchanged while enforcing a single nginx Basic Auth gate.

## Port layout
- External (LAN):
  - OctoPrint: `http://<pi>:5000/`
  - CAM0: `http://<pi>:8081/`
  - CAM1: `http://<pi>:8082/`
- Internal (loopback only):
  - OctoPrint: `http://127.0.0.1:5001/`
  - CAM0: `http://127.0.0.1:18081/`
  - CAM1: `http://127.0.0.1:18082/`

## Nginx config
- Site: `/etc/nginx/sites-available/octoprint-cameras.conf`
- Auth file: `/etc/nginx/octoprint.htpasswd`

To change credentials later:
```bash
sudo htpasswd /etc/nginx/octoprint.htpasswd <user>
sudo systemctl reload nginx.service
```

## Notes
- The cameras bind to `127.0.0.1` via `camX_bind` in `/etc/camera-streamer/camera-soft-stream.env`.
- OctoPrint runs on `127.0.0.1:5001` via its systemd unit.
- If OctoPrint asks for credentials again after nginx auth, keep OctoPrint login enabled; nginx only protects the perimeter.
