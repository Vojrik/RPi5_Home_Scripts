# Dual camera configuration (Raspberry Pi 5)

Tyto poznámky popisují aktuální softwarový MJPEG portál postavený nad `soft-stream.py`. Server běží na Raspberry Pi 5, obsluhuje dvě CSI kamery a vystavuje rozhraní pro OctoPrint/hlídací náhledy na portech 8081 (CAM0) a 8082 (CAM1).

## Požadavky

1. Zajisti Picamera2 stack z Raspberry Pi OS (balík `python3-picamera2` přetahuje i `libcamera`).  
2. Kamerové moduly musí být detekované příkazem:
   ```bash
   libcamera-still --list-cameras
   ```
   Pořadí výpisu určuje hodnoty `cam0_index`/`cam1_index` v env souboru.
3. Služby očekávají, že k dispozici je `/home/vojrik/Scripts/rpi_cameras` (spravuje tento repozitář) a `/etc/camera-streamer/` s konfigurací.

## Nasazení / aktualizace

1. Uprav `systemd/camera-soft-stream.env` podle požadovaného rozlišení, FPS, kvality a fokus režimu.
2. Z kořene repozitáře spusť:
   ```bash
   cd ~/Scripts/rpi_cameras
   ./deploy-soft-stream.sh
   ```
   Skript zkopíruje `soft-stream.py`, `measure_fps.py` a `README.md` do běhového adresáře, obnoví `/etc/camera-streamer/camera-soft-stream.env`, nahraje jednotky `camera-soft-cam{0,1}.service` a provede `systemctl daemon-reload && enable --now`.
3. Ověř, že služby běží:
   ```bash
   systemctl status camera-soft-cam0.service
   systemctl status camera-soft-cam1.service
   ```

## Ověření provozu

- Otevři `http://<pi>:8081/` (CAM0) a `http://<pi>:8082/` (CAM1). Landing page nabízí odkazy na `stream.mjpg` a `snapshot.jpg`.  
- `curl http://<pi>:8081/stream.mjpg --output /dev/null` během několika sekund potvrdí, že server posílá multipart MJPEG data.  
- Pro FPS měření použij bundled nástroj:
  ```bash
  python3 /home/vojrik/Scripts/rpi_cameras/measure_fps.py http://127.0.0.1:8082/stream.mjpg --frames 150
  ```
- Logy k autofocusu a (ne)dostupnosti kamery sleduj přes `journalctl -u camera-soft-camX.service -n 50`.

## Konfigurace env souboru

`systemd/camera-soft-stream.env` obsahuje sekce `cam0_*` a `cam1_*`:

- `camX_index` – pořadí podle `Picamera2.global_camera_info()`.
- `camX_width`, `camX_height`, `camX_fps` – parametry pro MJPEG stream; skript loguje vyjednané rozlišení, pokud HW vynutí změnu.
- `camX_port` – HTTP port (standardně 8081 / 8082).  
- `camX_snapshot_*` – parametry jednorázových snímků, které se pořizují mimo běžící stream.  
- `camX_autofocus` – zapíná volání `autofocus_cycle()` před startem streamu a před snapshotem.

Po úpravách env souboru stačí restartovat služby:
```bash
sudo systemctl restart camera-soft-cam0.service camera-soft-cam1.service
```

## Odstraňování problémů

- **Chybějící kamera** – pokud není připojena, server skončí s kódem 66 a systemd jednotka zůstane ve stavu `inactive (dead)`. Po připojení kabelu stačí `sudo systemctl restart camera-soft-camX.service`.  
- **Autofocus timeout** – sleduj logy; případně nastav `camX_autofocus=0` a ostři ručně.  
- **Nesprávné rozlišení** – log hlásí, když Picamera2 vynutí jiné rozlišení. Uprav `camX_width`/`height` na hodnotu, kterou kamera/ISP reálně podporuje.  
- **Port obsazený jinou službou** – změň `camX_port` a spusť deploy skript, aby se aktualizace propsala i do systemd jednotek.

## Legacy poznámka

Původní build `camera-streamer` s WebRTC endpointy jsme na Pi 5 opustili (žádný HW H.264). Soubory zůstávají jen jako historická reference ve staré větvi (`/home/vojrik/camera-streamer`). Nový repozitář obsahuje čistě soft-MJPEG řešení popsané výše.
