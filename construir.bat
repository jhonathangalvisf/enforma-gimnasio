@echo off
rem Construye el ejecutable y el instalador de Enforma en este PC con Windows.
rem Requisitos: Python 3.12 (py -3.12) e Inno Setup 6 (https://jrsoftware.org/isdl.php).
rem Uso: doble clic en construir.bat, o desde la consola en la carpeta del proyecto.
rem Resultado: dist\Enforma-Instalador-X.Y.Z.exe
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/6] Entorno de Python...
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv || goto error
)
call ".venv\Scripts\activate.bat" || goto error

echo [2/6] Dependencias...
python -m pip install --upgrade pip --quiet || goto error
pip install -r requirements.txt --quiet || goto error
pip install -e . --quiet || goto error
for /f %%v in ('python -c "import gimnasio; print(gimnasio.__version__)"') do set VERSION=%%v
echo        Version %VERSION%

echo [3/6] Manual en PDF...
python empaquetado\manual_pdf.py || goto error

echo [4/6] Ejecutable con PyInstaller (tarda unos minutos)...
pyinstaller empaquetado\enforma.spec --noconfirm --clean --log-level WARN || goto error

echo [5/6] Prueba de humo del ejecutable...
start "" /wait "dist\Enforma\Enforma.exe" --prueba-humo --reporte "dist\prueba_humo.txt"
type "dist\prueba_humo.txt"
findstr /c:"RESULTADO: OK" "dist\prueba_humo.txt" >nul || goto error

echo [6/6] Instalador con Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo No se encontro Inno Setup 6. Instalelo desde https://jrsoftware.org/isdl.php
    echo y vuelva a ejecutar construir.bat. El ejecutable ya esta en dist\Enforma\.
    goto fin
)
"%ISCC%" /Q /DVersion=%VERSION% empaquetado\enforma.iss || goto error

echo.
echo Listo: dist\Enforma-Instalador-%VERSION%.exe
goto fin

:error
echo.
echo *** La construccion fallo. Revise el mensaje de arriba. ***
pause
exit /b 1

:fin
pause
exit /b 0
