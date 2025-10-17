import psycopg2
import psycopg2.extras
import os
from flask import current_app

def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(current_app.config['DATABASE_URL'])
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise

# Utility functions for database operations
def execute_query(query, params=None, fetch=False):
    """Execute a database query"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if fetch else None)

    try:
        cursor.execute(query, params or ())
        if fetch:
            result = cursor.fetchall()
        else:
            result = None
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def execute_query_one(query, params=None):
    """Execute a query and fetch one result"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute(query, params or ())
        result = cursor.fetchone()
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()
