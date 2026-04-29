"""
Script to check the upload_status enum values in PostgreSQL database
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path to import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from utils.training_key_vault_reader import TrainingKeyVaultReader
    from utils.training_postgres_client import TrainingPostgresClient
except ImportError:
    print("ERROR: Could not import training utilities.")
    print("Make sure you're running from the correct directory.")
    sys.exit(1)

def check_enum_values():
    """Check what enum values are defined in the database"""
    
    # Get Key Vault URL
    key_vault_url = os.getenv("KEY_VAULT_URL")
    if not key_vault_url:
        print("ERROR: KEY_VAULT_URL not found in environment")
        sys.exit(1)
    
    # Initialize Key Vault reader
    kv_reader = TrainingKeyVaultReader(key_vault_url=key_vault_url)
    
    # Get connection string
    conn_str = kv_reader.get_secret("PostgreSQLConnectionString")
    if not conn_str:
        conn_str = os.getenv("PostgreSQLConnectionString")
    
    if not conn_str:
        print("ERROR: PostgreSQLConnectionString not found")
        sys.exit(1)
    
    # Get database name
    db_name = kv_reader.get_secret("PostgreSQLDatabase")
    if not db_name:
        db_name = os.getenv("PostgreSQLDatabase", "credit_scoring")
    
    # Create engine
    engine = create_engine(conn_str)
    
    print("=" * 60)
    print("Checking upload_status enum values in PostgreSQL")
    print("=" * 60)
    print()
    
    with engine.connect() as conn:
        # Method 1: Query enum values directly
        print("1. Enum values defined in database:")
        print("-" * 60)
        result = conn.execute(text("""
            SELECT 
                t.typname AS enum_name,
                e.enumlabel AS enum_value,
                e.enumsortorder AS sort_order
            FROM pg_type t 
            JOIN pg_enum e ON t.oid = e.enumtypid  
            WHERE t.typname = 'upload_status'
            ORDER BY e.enumsortorder;
        """))
        
        enum_values = []
        for row in result:
            enum_values.append(row.enum_value)
            print(f"   {row.enum_value}")
        
        print()
        print(f"   Total enum values: {len(enum_values)}")
        print()
        
        # Method 2: Check what values are currently used
        print("2. Current status values in training_uploads table:")
        print("-" * 60)
        result = conn.execute(text("""
            SELECT DISTINCT status, COUNT(*) as count
            FROM training_uploads
            GROUP BY status
            ORDER BY status;
        """))
        
        for row in result:
            print(f"   {row.status}: {row.count} records")
        
        print()
        
        # Method 3: Show enum definition
        print("3. Full enum definition:")
        print("-" * 60)
        result = conn.execute(text("""
            SELECT 
                'CREATE TYPE ' || t.typname || ' AS ENUM (' ||
                string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder) ||
                ');' AS enum_definition
            FROM pg_type t 
            JOIN pg_enum e ON t.oid = e.enumtypid  
            WHERE t.typname = 'upload_status'
            GROUP BY t.typname;
        """))
        
        for row in result:
            print(f"   {row.enum_definition}")
        
        print()
        print("=" * 60)
        print("Summary:")
        print(f"   Valid enum values: {', '.join(enum_values)}")
        print("=" * 60)

if __name__ == "__main__":
    try:
        check_enum_values()
    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
