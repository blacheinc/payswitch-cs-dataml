"""Test script to verify all imports work correctly"""
import sys
import os
from pathlib import Path

# Set up path like function_app.py does
CURRENT_DIR = Path(__file__).parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

print(f"Current directory: {CURRENT_DIR}")
print(f"Utils exists: {(CURRENT_DIR / 'utils').exists()}")
print(f"Scripts exists: {(CURRENT_DIR / 'scripts').exists()}")

try:
    from function_app import app
    print("✅ function_app imported")
    
    funcs = app.get_functions()
    print(f"✅ Found {len(funcs)} functions")
    
    from scripts.run_training_ingestion import run_single_message_from_function
    print("✅ run_single_message_from_function imported")
    
    print("\n✅ All imports successful!")
    
except Exception as e:
    print(f"\n❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
