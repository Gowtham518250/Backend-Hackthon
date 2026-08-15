#!/usr/bin/env python3
"""
Initialize the PostgreSQL database on Render.
This script creates all required tables and indexes.
"""

import os
import sys
from database import init_db

if __name__ == "__main__":
    try:
        print("Initializing PostgreSQL database on Render...")
        init_db()
        print("✓ Database initialized successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"✗ Failed to initialize database: {e}")
        sys.exit(1)
