"""Launch sample-only server. Bind loopback by default."""
import os
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
# Server-only secrets; never override securely injected deployment values.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

if __name__ == '__main__':
    from app.deployment import runtime_config, DeploymentConfigurationError
    try:
        settings = runtime_config()
    except DeploymentConfigurationError as error:
        raise SystemExit(str(error)) from None
    uvicorn.run('app.main:app', **settings)
