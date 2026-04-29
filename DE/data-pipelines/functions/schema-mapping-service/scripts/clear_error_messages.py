"""
Clear error messages from start-transformation subscription
This script consumes (removes) all messages with status = 'ERROR'
Uses Azure SDK, not Azure CLI
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.key_vault_reader import KeyVaultReader
from azure.servicebus import ServiceBusClient
import json

def main():
    kv_url = "https://blachekvruhclai6km.vault.azure.net/"
    
    print("="*60)
    print("Clearing Error Messages from Subscription")
    print("="*60)
    print()
    
    # Get connection string
    print("Retrieving Service Bus connection string...")
    try:
        with KeyVaultReader(key_vault_url=kv_url) as kv:
            conn_str = kv.get_secret("ServiceBusConnectionString")
        print("[OK] Connection string retrieved")
    except Exception as e:
        print(f"[ERROR] Failed to get connection string: {e}")
        sys.exit(1)
    
    print()
    
    # Connect to Service Bus
    print("Connecting to Service Bus...")
    client = ServiceBusClient.from_connection_string(conn_str)
    
    try:
        receiver = client.get_subscription_receiver(
            topic_name="data-ingested",
            subscription_name="start-transformation"
        )
        
        with receiver:
            print("Reading messages (will consume error messages)...")
            print()
            
            messages_read = []
            max_messages = 50  # Read up to 50 messages
            timeout_seconds = 10
            
            # Receive messages
            received_messages = receiver.receive_messages(
                max_message_count=max_messages,
                max_wait_time=timeout_seconds
            )
            
            print(f"Received {len(received_messages)} messages:")
            print("="*60)
            
            if len(received_messages) == 0:
                print("\n[OK] No messages in subscription")
            else:
                error_messages = []
                other_messages = []
                
                for msg in received_messages:
                    # Parse body
                    try:
                        body_str = None
                        
                        if hasattr(msg, 'body_as_str'):
                            try:
                                body_str = msg.body_as_str()
                            except Exception:
                                pass
                        
                        if body_str is None and hasattr(msg, 'body_as_bytes'):
                            try:
                                body_bytes = msg.body_as_bytes()
                                body_str = body_bytes.decode('utf-8') if isinstance(body_bytes, bytes) else str(body_bytes)
                            except Exception:
                                pass
                        
                        if body_str is None:
                            body = msg.body
                            if isinstance(body, bytes):
                                body_str = body.decode('utf-8')
                            else:
                                body_str = str(body)
                        
                        # Parse JSON
                        if body_str:
                            try:
                                body_json = json.loads(body_str)
                                status = body_json.get('status')
                                
                                if status == 'ERROR':
                                    error_messages.append((msg, body_json))
                                    print(f"\n[ERROR MESSAGE] Message ID: {msg.message_id}")
                                    print(f"  Training Upload ID: {body_json.get('training_upload_id', 'N/A')}")
                                    print(f"  Error: {body_json.get('error_report', {}).get('user_message', 'N/A')}")
                                else:
                                    other_messages.append((msg, body_json))
                                    print(f"\n[OTHER MESSAGE] Message ID: {msg.message_id}")
                                    print(f"  Status: {status or 'No status'}")
                            except json.JSONDecodeError:
                                other_messages.append((msg, None))
                                print(f"\n[NON-JSON MESSAGE] Message ID: {msg.message_id}")
                    except Exception as e:
                        other_messages.append((msg, None))
                        print(f"\n[ERROR PARSING] Message ID: {msg.message_id}, Error: {e}")
                    
                    messages_read.append(msg)
                
                print()
                print("="*60)
                print(f"Summary:")
                print(f"  Error messages: {len(error_messages)}")
                print(f"  Other messages: {len(other_messages)}")
                print(f"  Total: {len(messages_read)}")
                print()
                
                # Complete all messages (remove from queue)
                if messages_read:
                    print("Completing messages (removing from queue)...")
                    for msg in messages_read:
                        receiver.complete_message(msg)
                    print(f"[OK] {len(messages_read)} messages completed and removed")
                    
                    if error_messages:
                        print(f"[OK] {len(error_messages)} error messages cleared")
                    if other_messages:
                        print(f"[WARNING] {len(other_messages)} non-error messages were also removed")
                        print("  These should not have been in the subscription if the filter is working")
                else:
                    print("No messages to complete")
            
            print("="*60)
            print(f"Total messages processed: {len(messages_read)}")
            
    except Exception as e:
        print(f"\n[ERROR] Failed to read messages: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
