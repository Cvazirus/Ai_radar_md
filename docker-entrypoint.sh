#!/bin/sh
set -e

echo "Waiting for database..."
python -c "
import sys
import time
from sqlalchemy import create_engine, text
from app.config import settings

for attempt in range(30):
    try:
        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('Database is ready.')
        break
    except Exception as e:
        print(f'Database not ready (attempt {attempt + 1}/30): {e}')
        time.sleep(2)
else:
    print('Database did not become ready in time.', file=sys.stderr)
    sys.exit(1)
"

echo "Running database migrations..."
alembic upgrade head

echo "Seeding sources..."
python scripts/seed_sources.py

echo "Starting application..."
exec "$@"
