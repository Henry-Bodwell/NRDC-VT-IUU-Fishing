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
@REM echo [2023] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2023-01-01 --uri-file data\newsapi\2023-01-01_iuu_fishing_2025-11-04_10-26-38_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2023] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2023] Complete
@REM echo.

@REM REM 2022
@REM echo [2022] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2022-01-01 --uri-file data\newsapi\2022-01-01_iuu_fishing_2025-11-04_10-27-03_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2022] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2022] Complete
@REM echo.

@REM REM 2021
@REM echo [2021] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2021-01-01 --uri-file data\newsapi\2021-01-01_to_2021-12-31_iuu_fishing_2025-11-05_17-22-41_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2021] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2021] Complete
@REM echo.

@REM REM 2020
@REM echo [2020] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2020-01-01 --uri-file data\newsapi\2020-01-01_to_2020-12-31_iuu_fishing_2025-11-05_17-22-53_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2020] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2020] Complete
@REM echo.

@REM REM 2019
@REM echo [2019] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2019-01-01 --uri-file data\newsapi\2019-01-01_to_2019-12-31_iuu_fishing_2025-11-05_17-23-04_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2019] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2019] Complete
@REM echo.

@REM REM 2018
@REM echo [2018] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2018-01-01 --uri-file data\newsapi\2018-01-01_to_2018-12-31_iuu_fishing_2025-11-05_17-23-20_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2018] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2018] Complete
@REM echo.

@REM REM 2017
@REM echo [2017] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2017-01-01 --uri-file data\newsapi\2017-01-01_to_2017-12-31_iuu_fishing_2025-11-05_17-23-43_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2017] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2017] Complete
@REM echo.

@REM REM 2016
@REM echo [2016] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2016-01-01 --uri-file data\newsapi\2016-01-01_to_2016-12-31_iuu_fishing_2025-11-05_17-23-52_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2016] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2016] Complete
@REM echo.

@REM REM 2015
@REM echo [2015] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2015-01-01 --uri-file data\newsapi\2015-01-01_to_2015-12-31_iuu_fishing_2025-11-05_17-24-02_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2015] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2015] Complete
@REM echo.

@REM REM 2014
@REM echo [2014] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2014-01-01 --uri-file data\newsapi\2014-01-01_to_2014-12-31_iuu_fishing_2025-11-05_17-24-12_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2014] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2014] Complete
@REM echo.

@REM REM 2013
@REM echo [2013] Starting...
@REM python newsapi\fetch_newsapi.py --start-date 2013-01-01 --uri-file data\newsapi\2013-01-01_to_2013-12-31_iuu_fishing_2025-11-05_17-24-21_uris.json --fetch-articles
@REM if %errorlevel% neq 0 (
@REM     echo [2013] FAILED
@REM     pause
@REM     exit /b %errorlevel%
@REM )
@REM echo [2013] Complete
@REM echo.

echo ============================================================
echo All years completed successfully!
echo ============================================================
pause
