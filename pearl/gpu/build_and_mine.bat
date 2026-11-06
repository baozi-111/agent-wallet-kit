@echo off
cd /d "%~dp0"
call "E:\VS\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
set "PATH=%CUDA_PATH%\bin;%PATH%"
echo [GPU] building multi-find ...
nvcc -O3 -o mine_pearl_gpu.exe mine_pearl_gpu.cu
if errorlevel 1 exit /b 1
if exist "..\pearl-challenge.json" copy /Y "..\pearl-challenge.json" "pearl-challenge.json" >nul
echo [GPU] mining x16 ...
set PEARL_LIMIT_SEC=900
set PEARL_FIND_COUNT=16
mine_pearl_gpu.exe pearl-challenge.json
if exist pearl-solutions.json copy /Y pearl-solutions.json "..\pearl-solutions.json" >nul
exit /b %ERRORLEVEL%
