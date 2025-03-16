#!/bin/bash

# Extract cron schedule from config.yaml
CRON_SCHEDULE=$(python -c "
import yaml
with open('data_simulator/config/config.yaml') as f:
    config = yaml.safe_load(f)
print(config.get('cron_schedule', '0 0 * * *'))  # Default to midnight
")

# Write the cron job
echo "$CRON_SCHEDULE /usr/local/bin/python /app/cron_job.py >> /var/log/cron.log 2>&1" > /etc/cron.d/python-cron

# Set permissions
chmod 0644 /etc/cron.d/python-cron

# Apply the cron job
crontab /etc/cron.d/python-cron

# Create log file
touch /var/log/cron.log

# Start cron and tail logs
cron
tail -f /var/log/cron.log
