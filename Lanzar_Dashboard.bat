@echo off
title Air Guardian Launcher
echo ⚙️ Iniciando sistemas de Air Guardian...

:: Iniciar el Data Fetcher en una ventana separada y minimizada
echo 📡 Lanzando Sincronizador de Datos (data_fetcher)...
start /min "Air Guardian Fetcher" python data_fetcher.py

:: Iniciar el Dashboard de Streamlit
echo 🚂 Lanzando Dashboard Victoriano (app.py)...
python -m streamlit run app.py

echo.
echo ⚠️ Si cierras esta ventana, el Dashboard se detendra.
pause
