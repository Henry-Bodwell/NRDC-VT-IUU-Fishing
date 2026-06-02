#! /bin/bash
py -m webScraper.run_scraper --max-results 10 --sites undercurrent_news oceana noaa_fisheries --queries violence investigation coercion arrest charge indict fined enforce
py -m webScraper.run_scraper --max-results 10 --sites doj_gov monga_bay

py -m webScraper.run_scraper --import

py -m webScraper.upload_scraped_data --auth-token $AUTH_TOKEN --api-url https://iuudb.cs.vt.edu/ --all
