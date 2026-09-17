"""ECS-only configuration adapter embedded in the task command, not the image."""

import os
import re
import sys
import tempfile
from urllib.request import urlopen

from sqlalchemy.engine import URL


def database_url(environment, ca_path):
    """Construct a URL without shell interpolation of secret characters."""
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USERNAME", "DB_PASSWORD")
    if any(not environment.get(key) for key in required):
        raise ValueError("Required database configuration is missing")
    port = int(environment["DB_PORT"])
    if port != 5432:
        raise ValueError("Unsupported PostgreSQL port")
    return URL.create(
        "postgresql+psycopg",
        username=environment["DB_USERNAME"],
        password=environment["DB_PASSWORD"],
        host=environment["DB_HOST"],
        port=port,
        database=environment["DB_NAME"],
        query={"sslmode": "verify-full", "sslrootcert": str(ca_path), "connect_timeout": "10"},
    ).render_as_string(hide_password=False)


def download_ca(region):
    """Download only the public AWS RDS certificate bundle using verified HTTPS."""
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region):
        raise ValueError("Invalid AWS Region")
    address = f"https://truststore.pki.rds.amazonaws.com/{region}/{region}-bundle.pem"
    with urlopen(address, timeout=30) as response:
        bundle = response.read(1024 * 1024 + 1)
    if len(bundle) > 1024 * 1024 or b"-----BEGIN CERTIFICATE-----" not in bundle:
        raise ValueError("Invalid public RDS certificate bundle")
    # Only a public CA certificate is written; never a secret or connection URL.
    with tempfile.NamedTemporaryFile(suffix="-rds-ca.pem", delete=False) as certificate:
        certificate.write(bundle)
        return certificate.name


def main():
    try:
        certificate = download_ca(os.environ["AWS_REGION"])
        connection_url = database_url(os.environ, certificate)
        environment = dict(os.environ)
        environment["DATABASE_URL"] = connection_url
        environment.pop("DB_PASSWORD", None)
        environment.pop("DB_USERNAME", None)
        os.execvpe(
            sys.executable,
            [sys.executable, "-m", "uvicorn", "predictive_maintenance.api.main:app",
             "--host", "0.0.0.0", "--port", "8000"],
            environment,
        )
    except Exception:
        # Generic failure: no secret values, URLs or exception details in logs.
        print("API bootstrap unavailable: database configuration or public CA setup failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
