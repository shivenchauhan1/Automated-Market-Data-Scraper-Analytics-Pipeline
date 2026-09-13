#!/bin/bash
# ==============================================================================
# Linux Cron Automation Setup for Market Data Pipeline
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXEC="$(which python3 || which python)"
CRON_JOB="0 18 * * 1-5 cd $PROJECT_DIR && $PYTHON_EXEC main.py >> $PROJECT_DIR/pipeline_cron.log 2>&1"

echo "Configuring Linux Cron job for weekdays at 6:00 PM..."
(crontab -l 2>/dev/null | grep -Fv "main.py" ; echo "$CRON_JOB") | crontab -

echo "Cron schedule updated successfully:"
crontab -l | grep "main.py"
