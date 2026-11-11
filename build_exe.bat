@echo off
REM Build dist\CCMS_Tools.exe — standalone desktop version of the CCMS tools
REM Requires: py -m pip install pyinstaller edge-tts truststore imageio-ffmpeg

py -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name CCMS_Tools ^
    --collect-all imageio_ffmpeg ^
    --collect-submodules edge_tts ^
    --hidden-import truststore ^
    desktop_app.py
