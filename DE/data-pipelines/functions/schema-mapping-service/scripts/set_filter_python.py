"""
Set SQL filter on start-transformation subscription using Azure SDK
This is an alternative if Azure CLI is not working
"""

import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure.identity import DefaultAzureCredential
from azure.mgmt.servicebus import ServiceBusManagementClient
from azure.mgmt.servicebus.models import SqlFilter, Rule, SqlRuleAction
import json

# Configuration
SERVICE_BUS_NAMESPACE = "blache-cdtscr-dev-sb-y27jgavel2x32"
RESOURCE_GROUP = "blache-cdtscr-dev-data-rg"
TOPIC_NAME = "data-ingested"
SUBSCRIPTION_NAME = "start-transformation"
RULE_NAME = "ExcludeErrors"
FILTER_EXPRESSION = "[status] IS NULL OR [status] != 'ERROR'"

def main():
    print("="*60)
    print("Setting SQL Filter on Subscription (Python SDK)")
    print("="*60)
    print()
    
    # Get Azure credentials
    print("Authenticating with Azure...")
    credential = DefaultAzureCredential()
    
    # Create Service Bus management client
    print("Connecting to Service Bus management API...")
    subscription_id = None
    
    # Try to get subscription ID from environment variable first
    import os
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    
    if not subscription_id:
        # Try Azure CLI as fallback (but don't fail if it doesn't work)
        try:
            import subprocess
            result = subprocess.run(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                capture_output=True,
                text=True,
                timeout=5  # 5 second timeout
            )
            if result.returncode == 0 and result.stdout.strip():
                subscription_id = result.stdout.strip()
        except Exception:
            pass  # Azure CLI not available, continue
    
    if not subscription_id:
        # Try to get from command line argument
        parser = argparse.ArgumentParser(description='Set SQL filter on Service Bus subscription')
        parser.add_argument('--subscription-id', type=str, help='Azure Subscription ID')
        args, unknown = parser.parse_known_args()
        
        if args.subscription_id:
            subscription_id = args.subscription_id
        else:
            # Try to get from resource group using Azure SDK
            try:
                from azure.mgmt.resource import ResourceManagementClient
                resource_client = ResourceManagementClient(credential, "")
                # List subscriptions to find the one with our resource group
                subscriptions = list(resource_client.subscriptions.list())
                for sub in subscriptions:
                    try:
                        # Try to get the resource group
                        rg = resource_client.resource_groups.get(RESOURCE_GROUP)
                        if rg:
                            subscription_id = sub.subscription_id
                            print(f"[OK] Found subscription ID from resource group: {subscription_id[:8]}...")
                            break
                    except Exception:
                        continue
            except Exception as e:
                pass  # Fall through to error message
            
            if not subscription_id:
                # Last resort: error message
                print("[ERROR] Could not automatically get subscription ID.")
                print("\nPlease provide it as a command-line argument:")
                print("  python scripts\\set_filter_python.py --subscription-id <your-subscription-id>")
                print("\nOr set environment variable:")
                print("  $env:AZURE_SUBSCRIPTION_ID = '<your-subscription-id>'")
                print("\nTo find your subscription ID:")
                print("  - Azure Portal -> Subscriptions -> Copy Subscription ID")
                sys.exit(1)
    
    print(f"Subscription ID: {subscription_id}")
    print()
    
    client = ServiceBusManagementClient(credential, subscription_id)
    
    try:
        # Step 1: Check if subscription exists
        print(f"Step 1: Checking subscription '{SUBSCRIPTION_NAME}'...")
        try:
            subscription = client.subscriptions.get(
                resource_group_name=RESOURCE_GROUP,
                namespace_name=SERVICE_BUS_NAMESPACE,
                topic_name=TOPIC_NAME,
                subscription_name=SUBSCRIPTION_NAME
            )
            print(f"[OK] Subscription exists")
            print(f"   Filter Type: {subscription.filter_type}")
        except Exception as e:
            print(f"[ERROR] Subscription not found: {e}")
            sys.exit(1)
        
        # Step 2: List existing rules
        print(f"\nStep 2: Listing existing rules...")
        try:
            rules = client.rules.list_by_subscriptions(
                resource_group_name=RESOURCE_GROUP,
                namespace_name=SERVICE_BUS_NAMESPACE,
                topic_name=TOPIC_NAME,
                subscription_name=SUBSCRIPTION_NAME
            )
            
            rules_list = list(rules)
            if rules_list:
                print(f"[OK] Found {len(rules_list)} rule(s):")
                for rule in rules_list:
                    filter_expr = "N/A"
                    if rule.sql_filter and rule.sql_filter.sql_expression:
                        filter_expr = rule.sql_filter.sql_expression
                    print(f"   - {rule.name}: {filter_expr}")
                    
                    # Delete default rule if it exists
                    if rule.name == "$Default" or (rule.sql_filter and rule.sql_filter.sql_expression == "1=1"):
                        print(f"   Deleting default rule '{rule.name}'...")
                        client.rules.delete(
                            resource_group_name=RESOURCE_GROUP,
                            namespace_name=SERVICE_BUS_NAMESPACE,
                            topic_name=TOPIC_NAME,
                            subscription_name=SUBSCRIPTION_NAME,
                            rule_name=rule.name
                        )
                        print(f"[OK] Default rule deleted")
            else:
                print("[OK] No existing rules found")
        except Exception as e:
            print(f"[WARNING] Could not list rules: {e}")
        
        # Step 3: Create or update the filter rule
        print(f"\nStep 3: Creating/updating filter rule '{RULE_NAME}'...")
        sql_filter = SqlFilter(sql_expression=FILTER_EXPRESSION)
        rule = Rule(
            filter_type="SqlFilter",
            sql_filter=sql_filter
        )
        
        try:
            # Try to create
            client.rules.create_or_update(
                resource_group_name=RESOURCE_GROUP,
                namespace_name=SERVICE_BUS_NAMESPACE,
                topic_name=TOPIC_NAME,
                subscription_name=SUBSCRIPTION_NAME,
                rule_name=RULE_NAME,
                parameters=rule
            )
            print(f"[OK] Filter rule created/updated successfully")
        except Exception as e:
            print(f"[ERROR] Failed to create/update rule: {e}")
            sys.exit(1)
        
        # Step 4: Verify the rule
        print(f"\nStep 4: Verifying filter rule...")
        try:
            created_rule = client.rules.get(
                resource_group_name=RESOURCE_GROUP,
                namespace_name=SERVICE_BUS_NAMESPACE,
                topic_name=TOPIC_NAME,
                subscription_name=SUBSCRIPTION_NAME,
                rule_name=RULE_NAME
            )
            
            if created_rule.sql_filter:
                print(f"[OK] Filter verified:")
                print(f"   Rule Name: {created_rule.name}")
                print(f"   Filter: {created_rule.sql_filter.sql_expression}")
            else:
                print(f"[WARNING] Rule created but filter not found")
        except Exception as e:
            print(f"[WARNING] Could not verify rule: {e}")
        
        print("\n" + "="*60)
        print("Filter Set Successfully!")
        print("="*60)
        print("\nThe subscription will now:")
        print("  ✅ Accept messages with no status")
        print("  ✅ Accept messages with status != 'ERROR'")
        print("  ❌ Reject error messages (status = 'ERROR')")
        print("\nNext: Clear old error messages with:")
        print("  python scripts\\clear_error_messages.py")
        
    except Exception as e:
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
