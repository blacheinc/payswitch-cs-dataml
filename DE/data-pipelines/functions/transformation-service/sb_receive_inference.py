"""
Receive one message from the inference-request topic (local / integration debugging).

Requires a subscription that exists in your Service Bus namespace.
Set INFERENCE_REQUEST_SUBSCRIPTION to the real subscription name in Azure.

Connection string:
- SB_CONN, or
- TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING
"""
import json
import os
import sys

from azure.servicebus import ServiceBusClient

CONN = os.environ.get("SB_CONN") or os.environ.get(
    "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING"
)
TOPIC = os.environ.get("INFERENCE_REQUEST_TOPIC", "inference-request")
SUBSCRIPTION = os.environ.get("INFERENCE_REQUEST_SUBSCRIPTION", "orchestrator-sub")

if not CONN:
    print(
        "Set SB_CONN or TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING "
        "(copy from local.settings.json).",
        file=sys.stderr,
    )
    sys.exit(1)

with ServiceBusClient.from_connection_string(CONN) as client:
    receiver = client.get_subscription_receiver(
        topic_name=TOPIC,
        subscription_name=SUBSCRIPTION,
        max_wait_time=30,
    )
    with receiver:
        for msg in receiver:
            print("AppProps:", msg.application_properties)
            body = json.loads(str(msg))
            print("Body keys:", list(body.keys()))
            print("Request ID:", body.get("request_id"))
            print("Models to run:", body.get("models_to_run"))
            receiver.complete_message(msg)
            break
