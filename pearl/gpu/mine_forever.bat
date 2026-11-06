@echo off
REM Pearl GPU forever loop. Dual-buffer friendly. Does not sign.
REM each full batch of 16 is written to outbox\ and pearl-solutions-latest.json
REM then mining continues immediately (submit happens on the box).
cd /d "%~dp0"
call "E:\VS\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
set "PATH=%CUDA_PATH%\bin;%PATH%"

if not exist outbox mkdir outbox
if not exist mine_pearl_gpu.exe (
  echo [GPU] compiling mine_pearl_gpu.cu ...
  nvcc -O3 -o mine_pearl_gpu.exe mine_pearl_gpu.cu
  if errorlevel 1 exit /b 1
)

REM Prefer sibling challenge, else local
if exist "..\pearl-challenge.json" copy /Y "..\pearl-challenge.json" "pearl-challenge.json" >nul
if not exist "pearl-challenge.json" (
  echo Missing pearl-challenge.json — run challenge.py and copy the JSON here first.
  exit /b 1
)

set PEARL_LIMIT_SEC=900
set PEARL_FIND_COUNT=16
set PEARL_OUTBOX=outbox
REM Start nonce: bump across loops so we do not rehash the same region
set START=1793720000000000
if defined PEARL_START_NONCE set START=%PEARL_START_NONCE%

echo ============================================================
echo  Pearl GPU forever · identity comes from pearl-challenge.json
echo  This process finds nonces only. It does not sign or broadcast.
echo  outbox=%CD%\outbox
echo  Copy each outbox\pearl-batch-*.json to the submit inbox ^(PEARL_INBOX^).
echo  Do NOT transfer tokens while mining.
echo ============================================================

:loop
set PEARL_START_NONCE=%START%
echo.
echo ===== mining batch from nonce %START% =====
mine_pearl_gpu.exe pearl-challenge.json
if errorlevel 1 (
  echo miner returned error/timeout — retry after short pause
  timeout /t 2 /nobreak >nul
  goto loop
)

REM CU already wrote outbox\pearl-batch-*.json + pearl-solutions-latest.json
REM Also mirror latest to parent for easy CopyToBox
copy /Y pearl-solutions-latest.json ..\pearl-solutions-latest.json >nul 2>nul
copy /Y pearl-solutions.json ..\pearl-solutions.json >nul 2>nul

REM bump start by 2e10 via PowerShell (cmd set /a is 32-bit)
for /f %%N in ('powershell -NoProfile -Command "[string]([uint64]%START% + 20000000000)"') do set START=%%N
echo [GPU] batch done — continuing immediately (fire dual-buffer). next start=%START%
goto loop
