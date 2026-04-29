"""List subscriptions on a Service Bus topic (discover correct subscription names)."""
import os
import sys

try:
    from azure.servicebus.management import ServiceBusAdministrationClient
except ImportError as e:
    print("Need azure-servicebus with management support:", e, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    conn = os.environ.get("SB_CONN") or os.environ.get(
        "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING"
    )
    topic = os.environ.get("TRAINING_DATA_READY_TOPIC", "training-data-ready")
    if not conn:
        print(
            "Set SB_CONN or TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING.",
            file=sys.stderr,
        )
        sys.exit(1)
    client = ServiceBusAdministrationClient.from_connection_string(conn)
    try:
        subs = list(client.list_subscriptions(topic))
    except Exception as ex:
        print(f"Failed to list subscriptions on topic '{topic}': {ex}", file=sys.stderr)
        print(
            "If the topic does not exist, create topic + subscription in Azure first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not subs:
        print(f"No subscriptions on topic '{topic}'.")
        return
    print(f"Subscriptions on topic '{topic}':")
    for s in subs:
        print(f"  - {s.name}")


if __name__ == "__main__":
    main()
