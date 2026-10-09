import logging
import os
from contextlib import asynccontextmanager

# No library telemetry: nothing leaves the machine in the default mode.
for _var, _val in {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "ANONYMIZED_TELEMETRY": "False",
    "FASTAPI_OTEL_AUTO_CONFIGURE": "false",
}.items():
    os.environ.setdefault(_var, _val)

from fastapi import FastAPI  # noqa: E402

from app.api import admin, auth, chat, documents, manager  # noqa: E402
from app.config import get_settings  # noqa: E402

_INSECURE_SECRETS = {"change-me", "change-me-with-a-long-string-of-random-characters", "change-me-with-a-long-random-string"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    secret = get_settings().jwt_secret
    if secret in _INSECURE_SECRETS or len(secret) < 32:
        logging.getLogger("uvicorn.error").warning(
            "JWT_SECRET está com o valor de exemplo ou é curto demais. Defina uma string longa e aleatória no .env "
            "(ex.: python -c 'import secrets; print(secrets.token_urlsafe(48))')."
        )
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Plataforma de conhecimento interno",
    telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False},
)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(manager.router)


_INSECURE_SECRETS = {"change-me", "change-me-with-a-long-string-of-random-characters", "change-me-with-a-long-random-string"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
