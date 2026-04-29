"""
Upload Redis connection string to Azure Key Vault (one-off ops script).

Required environment variables (no secrets in source):
  KEY_VAULT_URL       e.g. https://your-vault.vault.azure.net/
  REDIS_HOST          e.g. your-cache.redis.cache.windows.net
  REDIS_ACCESS_KEY    primary/secondary key from the cache (paste at runtime only)

Optional:
  REDIS_PORT          default 6380 (TLS)
  SECRET_NAME         default RedisConnectionString
"""
import os
import sys

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

SECRET_NAME = os.getenv("SECRET_NAME", "RedisConnectionString")


def create_redis_connection_string(host: str, port: int, access_key: str) -> str:
    """Build redis:// URL for Azure Cache for Redis (non-TLS form; SSL normalized at runtime in app)."""
    return f"redis://:{access_key}@{host}:{port}"


def add_redis_to_keyvault() -> int:
    key_vault_url = (os.getenv("KEY_VAULT_URL") or "").strip()
    if key_vault_url and not key_vault_url.endswith("/"):
        key_vault_url += "/"
    redis_host = (os.getenv("REDIS_HOST") or "").strip()
    access_key = (os.getenv("REDIS_ACCESS_KEY") or "").strip()
    try:
        redis_port = int(os.getenv("REDIS_PORT", "6380"))
    except ValueError:
        print("ERROR: REDIS_PORT must be an integer", file=sys.stderr)
        return 1

    missing = [
        n
        for n, v in (
            ("KEY_VAULT_URL", key_vault_url),
            ("REDIS_HOST", redis_host),
            ("REDIS_ACCESS_KEY", access_key),
        )
        if not v
    ]
    if missing:
        print(
            "ERROR: Set these environment variables (do not commit values): "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("Adding Redis Connection String to Key Vault")
    print("=" * 60)

    try:
        print(f"\n1. Connecting to Key Vault: {key_vault_url}")
        credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_shared_token_cache_credential=False,
            exclude_visual_studio_code_credential=False,
            exclude_cli_credential=False,
            exclude_powershell_credential=False,
            exclude_managed_identity_credential=False,
            exclude_interactive_browser_credential=False,
        )
        client = SecretClient(vault_url=key_vault_url, credential=credential)

        print("\n2. Building connection string (key not printed)...")
        connection_string = create_redis_connection_string(
            host=redis_host, port=redis_port, access_key=access_key
        )
        print(f"   Target: redis://:***@{redis_host}:{redis_port}")

        print(f"\n3. Setting secret '{SECRET_NAME}'...")
        secret = client.set_secret(SECRET_NAME, connection_string)
        print("   OK — secret written.")
        print(f"   Secret ID: {secret.id}")

        print("\nSchema-mapping uses Redis only when SCHEMA_REGISTRY_ENABLE_REDIS=1.")
        return 0

    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(add_redis_to_keyvault())
