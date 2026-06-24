# Diagnostico de cortes - 2026-06-23

Contexto: revision remota del sistema Air Guardian / Air Cluster con:

- Nodo activo: `Air-Station`, Raspberry Pi Zero 2W, anteriormente en `192.168.0.227`.
- Nodo frio: `Air-Sensor`, Raspberry Pi Zero W, `192.168.0.149`.
- Fecha de revision: 2026-06-23 por la noche, zona Europe/London/local CEST en las Raspberry.

## Resumen

Hay dos problemas separados:

1. `Air-Station` no esta accesible en la red.
2. `Air-Sensor` esta vivo, pero tiene un servicio legacy fallando en bucle y errores WiFi del driver `brcmfmac`.

El archivo frio conserva datos de `Air-Station` hasta el 2026-06-21, pero desde entonces no entra nada nuevo.

## Estado de red

`Air-Sensor` responde:

- Hostname: `Air-Sensor`
- IP: `192.168.0.149`
- SSH: puerto 22 abierto
- Uptime observado: unos 12 dias

`Air-Station` no responde:

- IP conocida probada: `192.168.0.227`
- No responde a SSH.
- No aparece en `nmap -sn 192.168.0.0/24`.
- No aparece en `nmap -p 22 --open 192.168.0.0/24`.
- Nombres probados sin exito: `Air-Station.local`, `air-station.local`, `Air-Station`.

Conclusion provisional: `Air-Station` esta apagado, fuera de WiFi, con otra red/IP no detectada, colgado antes de red, o con alimentacion inestable. No se pudieron leer sus `journalctl` directamente.

## Datos archivados en Air-Sensor

Archivo revisado:

```text
/home/pi/air_archive/air_station/raw_samples.jsonl
```

Metadatos observados:

- Tamano: `289469579` bytes.
- Muestras parseadas: `233578`.
- Lineas corruptas o no parseables: `3`.
- Primera muestra: `2026-05-25T20:10:26.246650+00:00`.
- Ultima muestra: `2026-06-21T21:36:51.446064+00:00`.

La ultima muestra equivale a:

```text
2026-06-21 23:36:51 CEST
```

En la revision del 2026-06-23 por la noche, esto significa casi 48 horas sin datos nuevos de `Air-Station`.

Archivos en `/home/pi/air_archive/air_station/` vistos con ultima modificacion:

```text
baseline_state.json   2026-06-21 23:36:21 +0200
daily_summary.jsonl   2026-06-21 02:00:00 +0200
hourly_batches.jsonl  2026-06-21 23:12:41 +0200
latest_state.json     2026-06-21 23:37:21 +0200
raw_samples.jsonl     2026-06-21 23:36:51 +0200
```

## Huecos de muestreo detectados

El ritmo normal es una muestra cada 10 segundos. Se contaron huecos mayores de 30 segundos.

Total de huecos `>30s`: `8`.

Huecos principales:

```text
1792.0s  2026-06-03T14:40:59Z -> 2026-06-03T15:10:51Z
120.0s   2026-05-29T19:29:07Z -> 2026-05-29T19:31:07Z
98.7s    2026-05-25T20:10:46Z -> 2026-05-25T20:12:24Z
76.7s    2026-06-03T06:11:34Z -> 2026-06-03T06:12:51Z
68.7s    2026-06-05T06:00:54Z -> 2026-06-05T06:02:02Z
42.5s    2026-06-03T14:26:41Z -> 2026-06-03T14:27:24Z
41.3s    2026-06-03T14:40:18Z -> 2026-06-03T14:40:59Z
40.4s    2026-06-11T18:43:16Z -> 2026-06-11T18:43:56Z
```

Interpretacion: hasta el corte final del 2026-06-21, el archivo no muestra cortes constantes de escritura. La continuidad general es buena.

## Muestras por dia recientes

Esperado aproximado a 10 s: `8640` muestras/dia.

```text
2026-05-25 1370
2026-05-26 8641
2026-05-27 8640
2026-05-28 8640
2026-05-29 8629
2026-05-30 8640
2026-05-31 8640
2026-06-01 8640
2026-06-02 8640
2026-06-03 8447
2026-06-04 8640
2026-06-05 8634
2026-06-06 8640
2026-06-07 8641
2026-06-08 8640
2026-06-09 8640
2026-06-10 8640
2026-06-11 8635
2026-06-12 8640
2026-06-13 8640
2026-06-14 8640
2026-06-15 8640
2026-06-16 8640
2026-06-17 8640
2026-06-18 8640
2026-06-19 8640
2026-06-20 8639
2026-06-21 7782
```

`2026-06-21` queda corto porque los datos terminan a las `21:36:51 UTC`.

## Errores de sensor en los datos de Air-Station

Eventos recientes contados:

```text
CLEAN:           181000
OXIDISING_EVENT: 22010
VOC_EVENT:       14066
SENSOR_ERROR:    8291
MIXED_EVENT:     3887
NH3_EVENT:       2279
REDUCING_EVENT:  1236
SENSOR_WARMUP:   809
```

Validity reciente:

```text
OK:           224478
PARTIAL:      6454
SENSOR_ERROR: 1837
WARMUP:       809
```

Bloques largos de `SENSOR_ERROR`:

```text
3519 muestras  2026-06-07T01:22:15Z -> 2026-06-07T11:08:36Z  duracion ~9h46m
2927 muestras  2026-06-04T21:53:13Z -> 2026-06-05T06:00:54Z  duracion ~8h08m
1668 muestras  2026-06-16T00:24:37Z -> 2026-06-16T05:02:29Z  duracion ~4h38m
```

Interpretacion provisional: antes de la caida total, `Air-Station` ya tenia fallos largos de lectura/sensor. Hay que revisar logs reales del nodo activo cuando vuelva a estar accesible.

## Ultimo estado guardado de Air-Station

`latest_state.json` en el nodo frio quedo en estado bueno:

- Timestamp: `2026-06-21T21:37:21.448106+00:00`.
- `air_quality_state`: `GOOD`.
- `event_signature`: `CLEAN`.
- `validity.status`: `OK`.
- `bme690.heat_stable`: `true`.
- `logger_version`: `2026.05.29`.

Esto sugiere que el ultimo estado archivado no fue un error de sensor inmediato, sino una parada/desaparicion posterior del nodo activo o del mecanismo de archivo.

## Problema propio en Air-Sensor

`Air-Sensor` tiene un servicio legacy activo:

```text
air-logger.service - Air Guardian Local Logger (JSONL)
ExecStart=/home/pi/air/.venv/bin/python /home/pi/air/air_logger.py
Restart=always
RestartSec=5
```

Estado observado:

- `Active: activating (auto-restart) (Result: exit-code)`.
- Reinicios observados: mas de `12000`.
- Servicio disabled, pero arrancado y reiniciando.

Error repetido:

```text
RuntimeError: Unable to identify BME680 at 0x76 (IOError)
RuntimeError: Unable to identify BME680 at 0x77 (IOError)
OSError: [Errno 121] Remote I/O error
```

Interpretacion: el nodo frio intenta ejecutar el logger legacy de BME680 local, pero no detecta ningun BME680 en `0x76` ni `0x77`. Este bucle consume CPU, carga y ensucia el journal.

Accion recomendada: parar y deshabilitar `air-logger.service` en `Air-Sensor` si ya no se usa como nodo de medicion local.

## Errores WiFi en Air-Sensor

El journal del kernel muestra muchos errores del driver Broadcom:

```text
brcmfmac: brcmf_sdio_bus_rxctl: resumed on timeout
ieee80211 phy0: brcmf_cfg80211_dump_station: BRCMF_C_GET_ASSOCLIST failed, err=-110
brcmfmac: brcmf_sdio_read_control: last control frame is being processed.
ieee80211 phy0: brcmf_run_escan: error (-110)
ieee80211 phy0: brcmf_cfg80211_scan: scan error (-110)
brcmfmac: brcmf_sdio_isr: failed backplane access
```

Esto coincide con los timeouts de SSH vistos durante la revision. Parte fue agravada por una lectura pesada de diagnostico, que se paro manualmente, pero los errores WiFi indican un problema real o fragilidad del nodo frio.

## Incidente durante diagnostico

Se lanzo inicialmente un parseo completo que acumulaba el archivo JSONL en memoria en `Air-Sensor`; la Pi Zero quedo cargada y SSH empezo a dar timeout.

Procesos remotos identificados y terminados:

```text
python3 -  PID 5984
parent    PID 5983
```

Despues se repitio el analisis en streaming, sin acumular todas las muestras, y termino correctamente.

## Proximos pasos para manana

1. Revisar fisicamente `Air-Station`:
   - Alimentacion.
   - Cable USB/fuente.
   - Temperatura.
   - LED/actividad.
   - Si aparece en router/DHCP.

2. Si `Air-Station` arranca, sacar inmediatamente:

```bash
hostname
date
uptime
ip addr
systemctl --no-pager --full status air-station-logger.service air-station-led.service air-station-archive.timer air-station-archive.service
journalctl -u air-station-logger.service --since "2026-06-21" --no-pager
journalctl -u air-station-archive.service --since "2026-06-21" --no-pager
journalctl -p warning --since "2026-06-21" --no-pager
dmesg -T | grep -Ei "i2c|bme|mics|brcm|wlan|mmc|voltage|under"
```

3. En `Air-Sensor`, parar el logger legacy si ya no se necesita:

```bash
sudo systemctl stop air-logger.service
sudo systemctl disable air-logger.service
```

4. En `Air-Sensor`, revisar WiFi y alimentacion:

```bash
journalctl -k --since "2026-06-21" --no-pager | grep -Ei "brcm|wlan|mmc|voltage|under|timeout|error"
vcgencmd get_throttled
iw dev wlan0 link
```

5. Instalar `i2c-tools` en `Air-Sensor` si se quiere confirmar bus I2C:

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

6. Cuando `Air-Station` vuelva, comparar si tiene datos locales posteriores al `2026-06-21T21:36:51Z`:

```bash
cd /home/pi/BM680_2026/air_cluster
stat data/raw_samples.jsonl data/latest_state.json data/archive_status.json
tail -n 20 data/raw_samples.jsonl
cat data/archive_status.json
```

Si hay datos locales posteriores, el problema fue el archivado hacia `Air-Sensor`. Si tampoco hay datos locales posteriores, el problema fue parada/cuelgue del nodo activo o fallo de logger/sensor.
