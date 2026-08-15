#!/usr/bin/env python3
"""
Migration script to add 'customer' role to the database schema.
"""

import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it as an environment variable before running this migration."
    )

def migrate_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cursor = conn.cursor()
        
        # Drop the old constraint
        print("Dropping old CHECK constraint...")
        cursor.execute("""
            ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check
        """)
        conn.commit()
        print("✓ Old constraint dropped")
        
        # Add new constraint with 'customer' role
        print("Adding new CHECK constraint with 'customer' role...")
        cursor.execute("""
            ALTER TABLE users ADD CONSTRAINT users_role_check 
            CHECK(role IN ('owner', 'manager', 'employee', 'customer'))
        """)
        conn.commit()
        print("✓ New constraint added")
        
        # Update customer_users table constraint
        print("Updating customer_users constraint...")
        cursor.execute("""
            ALTER TABLE customer_users DROP CONSTRAINT IF EXISTS customer_users_role_check
        """)
        cursor.execute("""
            ALTER TABLE customer_users ADD CONSTRAINT customer_users_role_check 
            CHECK(role IN ('owner', 'manager', 'employee', 'customer'))
        """)
        conn.commit()
        print("✓ customer_users constraint updated")
        
        print("\n✓ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"✗ Migration error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate_db()