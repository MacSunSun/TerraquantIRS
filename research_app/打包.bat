@echo off
cd /d "%~dp0"

echo ============================================
echo  Build: Investment Research App
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause & exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller -q
)

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [1/3] Building exe...
python -m PyInstaller launcher.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo [ERROR] Build failed. See log above.
    pause & exit /b 1
)

echo [2/3] Assembling release folder...
set RELEASE=%~dp0..\Release
if exist "%RELEASE%" rmdir /s /q "%RELEASE%"
mkdir "%RELEASE%"

copy /y "dist\*.exe"       "%RELEASE%\" >nul
copy /y "app.py"           "%RELEASE%\" >nul
copy /y "requirements.txt" "%RELEASE%\" >nul
if exist "README.txt" copy /y "README.txt" "%RELEASE%\" >nul

xcopy /e /i /q "core"       "%RELEASE%\core\"       >nul
xcopy /e /i /q "pages"      "%RELEASE%\pages\"      >nul
xcopy /e /i /q "data"       "%RELEASE%\data\"       >nul
xcopy /e /i /q ".streamlit" "%RELEASE%\.streamlit\" >nul

for /d /r "%RELEASE%" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)

(
echo @echo off
echo python -m pip install -r requirements.txt
echo echo Done. Run the exe to start.
echo pause
) > "%RELEASE%\install.bat"

echo.
echo [3/3] Done!
echo Output: %RELEASE%
echo ============================================
pause