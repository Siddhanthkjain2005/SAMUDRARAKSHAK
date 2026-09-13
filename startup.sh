#!/usr/bin/env bash
# Azure App Service startup script for the backend
set -e
cd /home/site/wwwroot
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
