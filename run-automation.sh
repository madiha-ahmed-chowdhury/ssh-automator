#!/usr/bin/env bash
cd /home/madiha/ssh-poc
source venv/bin/activate
export API_KEY="bf5fc31ddac99b8aa3f48a00ca47d4beb2e5e2cc043fab21845ce19c602f71d4"
echo "=== run at $(date) ===" >> /home/madiha/ssh-poc/automation.log
python automate.py >> /home/madiha/ssh-poc/automation.log 2>&1
