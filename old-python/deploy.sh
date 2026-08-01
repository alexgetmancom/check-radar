#!/bin/bash
set -e

echo "⏳ Copying files to vm106..."
rsync -avz --exclude __pycache__ --exclude '*.pyc' --exclude .git --exclude .ruff_cache --exclude .env --exclude data ./ vm106:~/me-checks/

echo "🚀 Rebuilding and starting container on vm106..."
ssh vm106 "cd ~/me-checks && docker compose down && docker compose up -d --build"

echo "✅ Deployment completed successfully!"
