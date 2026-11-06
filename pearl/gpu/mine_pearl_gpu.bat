@echo off
cd /d "%~dp0"
setlocal
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
set "PATH=%CUDA_PATH%\bin;%PATH%"
echo [GPU] building ...
nvcc -O3 -o mine_pearl_gpu.exe mine_pearl_gpu.cu
if errorlevel 1 exit /b 1
if exist "..\pearl-challenge.json" copy /Y "..\pearl-challenge.json" "pearl-challenge.json" >nul
if not exist "pearl-challenge.json" exit /b 1
echo [GPU] mining ...
set PEARL_LIMIT_SEC=570
mine_pearl_gpu.exe pearl-challenge.json
if exist pearl-solution.json copy /Y pearl-solution.json "..\pearl-solution.json" >nul
exit /b %ERRORLEVEL%
