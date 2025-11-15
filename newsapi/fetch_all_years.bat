@echo off
REM Batch script to fetch articles for all years from URI files
REM Run from the project root directory

echo ============================================================
echo Fetching Articles Year by Year
echo ============================================================
echo.

REM 2025
echo [2025] Starting...
python newsapi\fetch_newsapi.py --start-date 2025-01-01 --uri-file data\newsapi\2025-01-01_iuu_fishing_2025-11-04_10-24-55_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2025] FAILED
    pause
    exit /b %errorlevel%
)
echo [2025] Complete
echo.

REM 2024
echo [2024] Starting...
python newsapi\fetch_newsapi.py --start-date 2024-01-01 --uri-file data\newsapi\2024-01-01_to_2024-12-31_iuu_fishing_2025-11-05_17-21-37_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2024] FAILED
    pause
    exit /b %errorlevel%
)
echo [2024] Complete
echo.

@REM REM 2023
echo [2023] Starting...
python newsapi\fetch_newsapi.py --start-date 2023-01-01 --uri-file data\newsapi\2023-01-01_iuu_fishing_2025-11-04_10-26-38_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2023] FAILED
    pause
    exit /b %errorlevel%
)
echo [2023] Complete
echo.

REM 2022
echo [2022] Starting...
python newsapi\fetch_newsapi.py --start-date 2022-01-01 --uri-file data\newsapi\2022-01-01_iuu_fishing_2025-11-04_10-27-03_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2022] FAILED
    pause
    exit /b %errorlevel%
)
echo [2022] Complete
echo.

REM 2021
echo [2021] Starting...
python newsapi\fetch_newsapi.py --start-date 2021-01-01 --uri-file data\newsapi\2021-01-01_to_2021-12-31_iuu_fishing_2025-11-05_17-22-41_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2021] FAILED
    pause
    exit /b %errorlevel%
)
echo [2021] Complete
echo.

REM 2020
echo [2020] Starting...
python newsapi\fetch_newsapi.py --start-date 2020-01-01 --uri-file data\newsapi\2020-01-01_to_2020-12-31_iuu_fishing_2025-11-05_17-22-53_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2020] FAILED
    pause
    exit /b %errorlevel%
)
echo [2020] Complete
echo.

REM 2019
echo [2019] Starting...
python newsapi\fetch_newsapi.py --start-date 2019-01-01 --uri-file data\newsapi\2019-01-01_to_2019-12-31_iuu_fishing_2025-11-05_17-23-04_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2019] FAILED
    pause
    exit /b %errorlevel%
)
echo [2019] Complete
echo.

REM 2018
echo [2018] Starting...
python newsapi\fetch_newsapi.py --start-date 2018-01-01 --uri-file data\newsapi\2018-01-01_to_2018-12-31_iuu_fishing_2025-11-05_17-23-20_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2018] FAILED
    pause
    exit /b %errorlevel%
)
echo [2018] Complete
echo.

REM 2017
echo [2017] Starting...
python newsapi\fetch_newsapi.py --start-date 2017-01-01 --uri-file data\newsapi\2017-01-01_to_2017-12-31_iuu_fishing_2025-11-05_17-23-43_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2017] FAILED
    pause
    exit /b %errorlevel%
)
echo [2017] Complete
echo.

REM 2016
echo [2016] Starting...
python newsapi\fetch_newsapi.py --start-date 2016-01-01 --uri-file data\newsapi\2016-01-01_to_2016-12-31_iuu_fishing_2025-11-05_17-23-52_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2016] FAILED
    pause
    exit /b %errorlevel%
)
echo [2016] Complete
echo.

REM 2015
echo [2015] Starting...
python newsapi\fetch_newsapi.py --start-date 2015-01-01 --uri-file data\newsapi\2015-01-01_to_2015-12-31_iuu_fishing_2025-11-05_17-24-02_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2015] FAILED
    pause
    exit /b %errorlevel%
)
echo [2015] Complete
echo.

REM 2014
echo [2014] Starting...
python newsapi\fetch_newsapi.py --start-date 2014-01-01 --uri-file data\newsapi\2014-01-01_to_2014-12-31_iuu_fishing_2025-11-05_17-24-12_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2014] FAILED
    pause
    exit /b %errorlevel%
)
echo [2014] Complete
echo.

REM 2013
echo [2013] Starting...
python newsapi\fetch_newsapi.py --start-date 2013-01-01 --uri-file data\newsapi\2013-01-01_to_2013-12-31_iuu_fishing_2025-11-05_17-24-21_uris.json --fetch-articles
if %errorlevel% neq 0 (
    echo [2013] FAILED
    pause
    exit /b %errorlevel%
)
echo [2013] Complete
echo.

echo ============================================================
echo All years completed successfully!
echo ============================================================
pause
