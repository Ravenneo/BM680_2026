# 🚂 Air Guardian Dashboard

Un sistema completo de recolección, sincronización y visualización (con estética Steampunk) de calidad del aire usando un sensor ambiental **BME680** junto con una matriz LED 5x5 acoplada a una Raspberry Pi.

## 🌟 Características
1. **IoT Edge Node (Raspberry Pi):** Lectura sub-segundo del sensor de gas (VOC), humedad, temperatura y presión. Cálculo de línea base adaptativa y *Score* de calidad del aire con traducción directa a colores LED vectorizables.
2. **Data Fetcher Resiliente:** Script en Python para PC/Servidor que descarga (`SFTP`) los registros `.jsonl` del nodo Pi resolviendo rotaciones de logs y desconexiones de red, optimizando transferencia con saltos asimétricos (*delta-sync*).
3. **Puesto de Mando (Dashboard Web):** Aplicación interactiva construida con `Streamlit` y decorada con un estilo Neo-Victoriano / Steampunk. Incluye:
    - **Panel "En Vivo":** Estadísticas y un widget con engranajes SVG animados que refleja al milisegundo e **inyectando el mismo algoritmo de mezcla de color RGB nativo** el estado de la Raspberry Pi.
    - **Historial Atmosférico:** Selección de granularidad de registro y análisis visual profundo (Cálculos de correlación matemática AI-driven entre Humedad vs Calidad de Aire).
4. **RAVEN FIELD STATION:** Consola terminal premium con `Rich` para `tmux`/SSH que combina el nodo BME680 con un contador Geiger-Muller local, mostrando telemetría ambiental, radiación, salud de sesión y eventos recientes en vivo.

## 📂 Estructura del Proyecto

```text
BM680_2026/
├── app.py                      # Dashboard Web en Streamlit (El Panel Neo-Victoriano)
├── data_fetcher.py             # Script de Sincronización IoT (Descarga los baselines desde la Pi)
├── requirements.txt            # Dependencias del lado PC
├── .gitignore
├── README.md
├── field_station/              # Dashboard terminal Rich + integración Geiger
│   ├── README.md
│   ├── requirements.txt
│   ├── arduino/
│   │   └── GeigerUsbQuiet/
│   │       └── GeigerUsbQuiet.ino
│   └── tools/
│       ├── raven_field_station.py
│       ├── geiger_serial_logger.py
│       ├── air_sensor_logger.py
│       └── start_raven_field_station.sh
└── raspberry_pi_scripts/       # Scripts ORIGINALES que corren dentro de la Raspberry Pi
    ├── air_logger.py           # Demonio de lectura primaria (Salida CSV/JSONL)
    ├── led_tiles_bme680.py     # Demonio visual (Matriz 5x5 RGB interactiva)
    └── start_air_system.sh     # Script de arranque en la Pi
```

> **Nota:** Los archivos de datos `air_samples.jsonl` y `air_batches_15m.jsonl` generados dinámicamente son ignorados por defecto en el repositorio para no subir pesos innecesarios de la bitácora.

---

## ⚙️ Guía de Instalación y Despliegue

### 1. Configuración de la Raspberry Pi (IoT Node)
Estos scripts están diseñados para correr en una Raspberry Pi con los sensores pHAT BME680 y Pimoroni RGB Matrix 5x5 conectados por GPIO/I2C.
1. Transfiere o clona la carpeta `raspberry_pi_scripts/` dentro de `/home/pi/air/`.
2. Otorga permisos de ejecución al lanzador:
   ```bash
   chmod +x /home/pi/air/start_air_system.sh
   ```
3. Ejecuta el sistema:
   ```bash
   ./start_air_system.sh
   ```
   *Esto lanzará el registro en background y encenderá la matriz indicando el "Warmup" (Precalentamiento azul/celeste).*

### 🚀 Lanzamiento Rápido (Windows)
Para tu comodidad, he incluido un archivo llamado `Lanzar_Dashboard.bat`. Solo tienes que hacer **doble clic** en él y hará todo por ti: 
1. Abrirá el sincronizador en segundo plano.
2. Lanzará el Dashboard en tu navegador.

### 2. Configuración Manual de la Estación de Comando (PC Local)
La PC es la encargada de hacer *pull* de los datos y renderizar el Dashboard al usuario.

1. **Instalar dependencias de Python:**
   Asegúrate de tener Python instalado y ejecuta:
   ```bash
   pip install paramiko streamlit pandas
   ```
2. **Ejecutar el Sincronizador de Datos:**
   Abre una terminal y déjalo corriendo. Este mantendrá una conexión viva con tu Raspberry Pi (IP `192.168.0.149` configurada por defecto) buscando nuevos tramos.
   ```bash
   python data_fetcher.py
   ```
3. **Desplegar el Dashboard Steampunk:**
   En una _nueva_ ventana de terminal, lanza la app web:
   ```bash
    python -m streamlit run app.py
    ```
    La aplicación se abrirá en tu navegador nativo revelando el panel. ¡Asegúrate de encender la opción de auto-sincronización en el panel lateral!

### 3. RAVEN FIELD STATION (Terminal / tmux)
La vista terminal vive en `field_station/` y está pensada para una sesión SSH o `tmux` grande.

```bash
pip install -r requirements.txt
python3 field_station/tools/raven_field_station.py
```

También puedes lanzar los loggers auxiliares para poblar los estados locales:

```bash
cd field_station
python3 tools/geiger_serial_logger.py --port /dev/ttyUSB0 --baud 9600
python3 tools/air_sensor_logger.py --host 192.168.0.149 --user pi
```

La consola lee:

```text
/tmp/geiger_state.json
/tmp/geiger_serial.log
/tmp/air_state.json
/tmp/air_sensor.log
```

Más detalles en [`field_station/README.md`](field_station/README.md).

## 🔧 Licencia & Contribución
Proyecto creado para experimentación IoT, Steampunk Aesthetics y monitoreo ambiental profundo. Siéntete libre de clonarlo, romperlo y arreglarlo. ⚙️🚂
