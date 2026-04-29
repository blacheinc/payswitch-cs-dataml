"""
Test if all imports work correctly
This simulates what the function runtime does when loading the function
"""

import sys
import os
from pathlib import Path

# Add parent directory to path (where function_app.py is)
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Set environment variable
os.environ['KEY_VAULT_URL'] = 'https://blachekvruhclai6km.vault.azure.net/'

print("Testing imports...")
print("="*60)
print(f"Python path: {sys.path[:3]}")
print()

try:
    print("1. Importing azure.functions...")
    import azure.functions as func
    print("   [OK] azure.functions imported")
except Exception as e:
    print(f"   [ERROR] Failed to import azure.functions: {e}")
    sys.exit(1)

try:
    print("2. Importing function_app...")
    from function_app import app, schema_mapping_orchestrator
    print("   [OK] function_app imported")
    print(f"   [OK] Function app created: {app}")
    print(f"   [OK] Function registered: schema_mapping_orchestrator")
except Exception as e:
    print(f"   [ERROR] Failed to import function_app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("3. Importing orchestrator...")
    from orchestrator import get_orchestrator
    print("   [OK] orchestrator imported")
except Exception as e:
    print(f"   [ERROR] Failed to import orchestrator: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("="*60)
print("[SUCCESS] All imports successful!")
print("The function should be able to start.")
