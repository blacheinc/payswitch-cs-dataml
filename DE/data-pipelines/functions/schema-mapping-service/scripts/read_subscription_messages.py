"""
Script to READ (consume) messages from Service Bus subscription
This will actually remove messages from the queue so we can see them
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.key_vault_reader import KeyVaultReader
from azure.servicebus import ServiceBusClient
import json

def read_messages():
    """Read messages from the start-transformation subscription"""
    kv_url = "https://blachekvruhclai6km.vault.azure.net/"
    
    print("="*60)
    print("READING Messages from Subscription (will consume them)")
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
            print("Reading messages (max 10, will consume them)...")
            print()
            
            messages_read = []
            max_messages = 10
            timeout_seconds = 5
            
            # Receive messages
            received_messages = receiver.receive_messages(
                max_message_count=max_messages,
                max_wait_time=timeout_seconds
            )
            
            print(f"Received {len(received_messages)} messages:")
            print("="*60)
            
            if len(received_messages) == 0:
                print("\n[WARNING] No messages received!")
                print("This means:")
                print("  1. No messages in the subscription")
                print("  2. Messages were already consumed")
                print("  3. Messages expired")
            else:
                for i, msg in enumerate(received_messages, 1):
                    print(f"\n--- Message {i} ---")
                    print(f"Message ID: {msg.message_id}")
                    print(f"Session ID: {msg.session_id}")
                    print(f"Content Type: {msg.content_type}")
                    print(f"Application Properties: {dict(msg.application_properties) if msg.application_properties else 'None'}")
                    
                    # Parse body
                    try:
                        # Try different methods to get body
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
                            elif hasattr(body, '__iter__') and not isinstance(body, (str, bytes)):
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
                                print(f"Body (raw, not JSON): {body_str}")
                        else:
                            print(f"Body: (empty or could not read)")
                    except Exception as e:
                        print(f"Body (error parsing): {str(e)}")
                    
                    messages_read.append(msg)
                    print()
            
            # Complete the messages (remove from queue)
            if messages_read:
                print("="*60)
                print(f"Completing {len(messages_read)} messages (removing from queue)...")
                for msg in messages_read:
                    receiver.complete_message(msg)
                print(f"[OK] {len(messages_read)} messages completed and removed from queue")
            else:
                print("="*60)
                print("No messages to complete")
            
            print("="*60)
            print(f"Total messages read: {len(messages_read)}")
            
    finally:
        client.close()

if __name__ == "__main__":
    try:
        read_messages()
    except Exception as e:
        print(f"\n[ERROR] Failed to read messages: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
