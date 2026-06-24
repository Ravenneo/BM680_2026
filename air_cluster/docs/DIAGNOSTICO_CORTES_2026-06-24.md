# Diagnostico de cortes - 2026-06-24

Contexto: revision remota de `Air-Station` (`192.168.0.227`) y `Air-Sensor`
(`192.168.0.149`) tras los cortes observados el 2026-06-23.

## Estado actual

- Ambos nodos responden por red y SSH.
- `Air-Station` escribe muestras locales actuales.
- `Air-Sensor` ya no tiene activo el servicio legacy `air-logger.service`.
- `health_check.py` en `Air-Station` termina con `ok: true` tras forzar un
  archivado manual.

## Hallazgos principales

1. Hubo un hueco grande de muestreo local en `Air-Station`:

```text
2026-06-23T21:24:13Z -> 2026-06-24T14:09:12Z
duracion: ~60299 s (~16 h 45 min)
```

2. En las ultimas 1999 muestras parseables revisadas:

```text
validity.status: OK 1999
errores de sensor: ninguno
eventos: CLEAN 1660, VOC_EVENT 264, OXIDISING_EVENT 46, NH3_EVENT 28, MIXED_EVENT 1
```

Interpretacion: el problema actual no es que el logger este registrando errores
de sensor continuos. El fallo visible fue una interrupcion larga de escritura o
ejecucion, seguida de recuperacion.

3. Hay corrupcion en `raw_samples.jsonl`:

```text
linea nula en muestra reciente: 2759 bytes de 0x00
```

Esto sugiere corte abrupto, apagado, reinicio o escritura interrumpida. Los
consumidores de JSONL deben seguir tolerando lineas no parseables.

4. `Air-Station` y `Air-Sensor` muestran boot el `2026-06-23 23:22 CEST`.
No hay boots anteriores disponibles en `journalctl --list-boots`, asi que no se
puede reconstruir desde journal el motivo exacto del reinicio anterior.

5. `Air-Station` no muestra undervoltage actual:

```text
vcgencmd get_throttled -> throttled=0x0
```

Esto solo descarta undervoltage historico registrado en el estado actual del
firmware; no prueba que nunca haya habido un corte de alimentacion.

6. Los reinicios de `air-station-led.service` son esperados por configuracion:

```text
led.reinit_interval_seconds: 300
```

El servicio LED sale con codigo 0 cada 300 s para rearmar el controlador y
systemd lo arranca otra vez. Esto infla el contador de restart, pero no es un
crash.

7. El archivo de respaldo en `Air-Sensor` estaba congelado desde:

```text
2026-06-21T21:36:51Z
```

El `archive_push.py` fallaba desde `Air-Station` hacia `Air-Sensor` con:

```text
No route to host
TimeoutExpired en ssh mkdir -p /home/pi/air_archive/air_station
```

Sin embargo, una prueba posterior con la misma clave SSH desde `Air-Station`
hacia `Air-Sensor` autentico correctamente, aunque lenta. El archivado manual
finalmente completo:

```text
raw_samples.jsonl     29.831 s
hourly_batches.jsonl   2.344 s
daily_summary.jsonl    2.121 s
latest_state.json      2.124 s
baseline_state.json    2.144 s
```

Tras eso, `archive_status.json` quedo `ok: true` y el archivo de
`Air-Sensor` contiene muestras actuales del 2026-06-24.

## Conclusion provisional

Hay tres problemas distintos:

1. Corte/reinicio real del sistema alrededor del `2026-06-23 23:22 CEST`, con
   un hueco de muestras de casi 16 h 45 min.
2. Enlace WiFi/SSH fragil entre `Air-Station` y `Air-Sensor`; ping puede
   funcionar mientras SSH/rsync se queda colgado o tarda mucho.
3. Confusion por los reinicios del LED cada 300 s, que son voluntarios por
   configuracion y no explican la perdida de muestras.

Los sensores estan leyendo bien ahora. Las ultimas muestras revisadas tienen
`validity.status=OK` y sin errores.

## Acciones realizadas

- Se comprobo `systemctl` de logger, LED y archivado.
- Se comprobo `journalctl` del boot actual.
- Se verifico conectividad en ambos sentidos entre las Raspberry.
- Se ejecuto `archive_push.py` manualmente hasta dejar el respaldo actualizado.
- Se verifico `health_check.py --json`, que termino con `ok: true`.
- Se desplego `archive_push.py` con reintentos para SSH/rsync transitorios.
- Se desactivo WiFi power-save en `Air-Station` y `Air-Sensor`:

```text
iw dev wlan0 get power_save -> Power save: off
NetworkManager 802-11-wireless.powersave -> disable
```

- Se instalo journald persistente en ambos nodos para conservar boots futuros.
- Se anadio `air-station-health.timer` para escribir snapshots periodicos en:

```text
/home/pi/BM680_2026/air_cluster/data/health_check.jsonl
```

- Se bajo el timer de archivado de 1 hora a 10 minutos.
- Se cambio el rearme del LED de 300 s a 3600 s para reducir ruido en
  `systemctl` y en el journal.
- Se consolido en el repo local el codigo remoto que ya estaba desplegado:
  validacion/reconexion BME690 y recuperacion controlada de RGB Matrix.
- `Air-Sensor` quedo con `air-logger.service` disabled e inactive.

## Siguientes acciones recomendadas

1. Vigilar durante unas horas `health_check.jsonl`, `archive_status.json` y
   `journalctl -u NetworkManager` para confirmar que no vuelven los DHCP
   restarts.
2. Si siguen los cortes WiFi, considerar IP fija o reserva DHCP en el router
   para `192.168.0.227` y `192.168.0.149`, y/o acercar nodos al AP.
3. Revisar fisicamente alimentacion/cableado de ambas Pi si reaparecen lineas
   nulas en JSONL o boots simultaneos.
4. Evitar diagnosticos que transfieran o parseen los 297 MB completos por SSH
   cuando la WiFi este inestable; usar analisis por ventanas o scripts locales
   en streaming.
