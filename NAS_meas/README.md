# NAS INA219

Skript pro čtení INA219 přes I2C a publikaci do Home Assistantu přes MQTT autodiscovery.

## Požadavky

- I2C povolené na Raspberry Pi
- Balíčky: `python3-smbus` (nebo `smbus2`) a `python3-paho-mqtt`

Příklad instalace:

```bash
sudo apt install python3-smbus python3-paho-mqtt
```

## Konfigurace

Konfiguruje se přes soubor `.env` ve stejné složce. Vzor je v `.env.example`.

Použité parametry:

- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`
- `MQTT_BASE_TOPIC` (default `nas/ina219`)
- `MQTT_DISCOVERY_PREFIX` (default `homeassistant`)
- `MQTT_DEVICE_ID`, `MQTT_DEVICE_NAME`
- `PMIC_MQTT_BASE_TOPIC` (default `rpi_supply`)
- `PMIC_MQTT_DEVICE_ID`, `PMIC_MQTT_DEVICE_NAME`
- `I2C_BUS` (default `1`)
- `I2C_ADDRESS` (volitelné; když není, skript skenuje 0x40-0x4F)
- `PUBLISH_INTERVAL_SEC` (default `1.0`)

Hardware konfigurace je nastavena přímo ve skriptu:

- PGA 80 mV (vystačí na ~5.16 A s daným Rshunt)
- interní průměrování 128 vzorků
- `MAX_CURRENT_A = 4.0`
- `RSHUNT_OHM = 0.015493`

Skript používá zámek `/home/vojrik/.i2c-1.lock`, aby se zabránilo kolizím s jinými procesy na I2C.

## Ruční spuštění

```bash
/home/vojrik/Scripts/NAS_meas/ina219-monitor.py
```

Skript bude cyklicky vypisovat napětí, proud a výkon do terminálu.

Pro PMIC hodnoty Raspberry Pi 5:

```bash
/home/vojrik/Scripts/NAS_meas/pi-pmic-monitor.py
```

Skript čte `vcgencmd pmic_read_adc` a publikuje `EXT5V_V`, `3V3_SYS_V`, `3V3_SYS_A`.
PMIC senzory jsou publikované pod `PMIC_MQTT_BASE_TOPIC` a mají vlastní device ID/name.

## MQTT autodiscovery

Skript publikuje tři senzory:

- `nas/ina219/voltage` (V)
- `nas/ina219/current` (A)
- `nas/ina219/power` (W)

Home Assistant senzory objeví přes MQTT discovery prefix `homeassistant`.

## Systemd služba

Služba je připravená v souboru `nas-ina219.service`:

```bash
sudo cp /home/vojrik/Scripts/NAS_meas/nas-ina219.service /etc/systemd/system/nas-ina219.service
sudo systemctl daemon-reload
sudo systemctl enable --now nas-ina219.service
```

Stav:

```bash
systemctl status nas-ina219.service
```

Pro PMIC je připravená služba `nas-pmic.service`:

```bash
sudo cp /home/vojrik/Scripts/NAS_meas/nas-pmic.service /etc/systemd/system/nas-pmic.service
sudo systemctl daemon-reload
sudo systemctl enable --now nas-pmic.service
```

Stav:

```bash
systemctl status nas-pmic.service
```
