"""
Script to peek at messages in Service Bus subscription
This helps verify messages are actually there and in the correct format
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.key_vault_reader import KeyVaultReader
from azure.servicebus import ServiceBusClient
import json

def peek_messages():
    """Peek at messages in the start-transformation subscription"""
    kv_url = "https://blachekvruhclai6km.vault.azure.net/"
    
    print("="*60)
    print("Peeking at Messages in Subscription")
    print("="*60)
    print()
    
    # Get connection string
    print("Retrieving Service Bus connection string...")
    with KeyVaultReader(key_vault_url=kv_url) as kv:
        conn_str = kv.get_secret("ServiceBusConnectionString")
    
    print("[OK] Connection string retrieved")
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
            print("Peeking at messages (max 10)...")
            messages = receiver.peek_messages(max_message_count=10)
            
            print(f"\nFound {len(messages)} messages:")
            print("="*60)
            
            if len(messages) == 0:
                print("\n[WARNING] No messages found in subscription!")
                print("This could mean:")
                print("  1. Messages were already consumed by the function")
                print("  2. Messages were never delivered to the subscription")
                print("  3. Messages expired or were moved to dead letter queue")
            else:
                for i, msg in enumerate(messages, 1):
                    print(f"\n--- Message {i} ---")
                    print(f"Message ID: {msg.message_id}")
                    print(f"Session ID: {msg.session_id}")
                    print(f"Content Type: {msg.content_type}")
                    print(f"Application Properties: {dict(msg.application_properties) if msg.application_properties else 'None'}")
                    
                    # Parse body - handle different SDK versions
                    try:
                        body_str = None
                        
                        # Try body_as_str() first (newer SDK)
                        if hasattr(msg, 'body_as_str'):
                            try:
                                body_str = msg.body_as_str()
                            except Exception:
                                pass
                        
                        # Try body_as_bytes() and decode
                        if body_str is None and hasattr(msg, 'body_as_bytes'):
                            try:
                                body_bytes = msg.body_as_bytes()
                                body_str = body_bytes.decode('utf-8') if isinstance(body_bytes, bytes) else str(body_bytes)
                            except Exception:
                                pass
                        
                        # Fallback to message.body
                        if body_str is None:
                            body = msg.body
                            if isinstance(body, bytes):
                                body_str = body.decode('utf-8')
                            elif hasattr(body, '__iter__') and not isinstance(body, (str, bytes)):
                                # Handle generators/iterables
                                try:
                                    chunks = list(body)
                                    if chunks and isinstance(chunks[0], bytes):
                                        body_str = b''.join(chunks).decode('utf-8')
                                    else:
                                        body_str = ''.join(str(chunk) for chunk in chunks)
                                except Exception:
                                    body_str = str(body)
                            else:
                                body_str = str(body)
                        
                        # Try to parse as JSON
                        if body_str:
                            try:
                                body_json = json.loads(body_str)
                                print(f"Body (JSON):")
                                print(json.dumps(body_json, indent=2))
                            except json.JSONDecodeError:
                                print(f"Body (raw, not JSON): {body_str[:500]}")
                        else:
                            print(f"Body: (empty or could not read)")
                    except Exception as e:
                        print(f"Body (error parsing): {str(e)}")
                        import traceback
                        traceback.print_exc()
                    
                    print()
            
            print("="*60)
            print(f"Total messages peeked: {len(messages)}")
            
    finally:
        client.close()

if __name__ == "__main__":
    try:
        peek_messages()
    except Exception as e:
        print(f"\n[ERROR] Failed to peek messages: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
