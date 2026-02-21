import time
import paramiko
import os
import socket
import logging

# Configuración del logging para monitorear el script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)

# Configuración de conexión y rutas
HOST = "192.168.0.149"
USER = "pi"
PASSWORD = "pi"
FILES_TO_SYNC = [
    {"remote": "/home/pi/air/data/air_batches_15m.jsonl", "local": "air_batches_15m.jsonl"},
    {"remote": "/home/pi/air/data/air_samples.jsonl", "local": "air_samples.jsonl"}
]
CHECK_INTERVAL_SEC = 30
CHUNK_SIZE = 8192

def sync_data():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    while True:
        sftp = None
        try:
            logging.info(f"Conectando a {HOST} vía SSH...")
            ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)
            sftp = ssh.open_sftp()
            logging.info("Conexión SSH y SFTP establecida correctamente.")
            
            while True:
                for file_info in FILES_TO_SYNC:
                    remote_path = file_info["remote"]
                    local_path = file_info["local"]
                    
                    # Obtener el tamaño del archivo local si ya existe
                    local_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
                    
                    try:
                        remote_stat = sftp.stat(remote_path)
                        remote_size = remote_stat.st_size
                        
                        if remote_size > local_size:
                            logging.info(f"Nuevos datos en {local_path}. Sincronizando...")
                            with sftp.open(remote_path, 'rb') as remote_file:
                                remote_file.seek(local_size)
                                with open(local_path, 'ab') as local_file:
                                    while True:
                                        chunk = remote_file.read(CHUNK_SIZE)
                                        if not chunk:
                                            break
                                        local_file.write(chunk)
                            logging.info(f"Sincronización de {local_path} completada.")
                        elif remote_size < local_size:
                            logging.warning(f"Rotación detectada en {remote_path}. Re-descargando...")
                            sftp.get(remote_path, local_path)
                    except IOError as e:
                        logging.error(f"Error con {remote_path}: {e}")
                
                time.sleep(CHECK_INTERVAL_SEC)

                
        except (paramiko.SSHException, socket.error) as e:
            logging.error(f"Error de conexión de red/SSH: {e}. Reintentando en {CHECK_INTERVAL_SEC} segundos...")
            time.sleep(CHECK_INTERVAL_SEC)
        except Exception as e:
            logging.error(f"Error inesperado: {e}")
            time.sleep(CHECK_INTERVAL_SEC)
        finally:
            if sftp:
                try:
                    sftp.close()
                except Exception:
                    pass
            try:
                ssh.close()
            except Exception:
                pass

if __name__ == "__main__":
    logging.info("Iniciando Data Fetcher para Air Guardian Dashboard...")
    sync_data()
