import os

# No library telemetry: nothing leaves the machine in the default mode.
for _var, _val in {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "ANONYMIZED_TELEMETRY": "False",
    "FASTAPI_OTEL_AUTO_CONFIGURE": "false",
}.items():
    os.environ.setdefault(_var, _val)

from fastapi import FastAPI  # noqa: E402

from app.api import admin, auth, documents  # noqa: E402

app = FastAPI(
    title="Plataforma de conhecimento interno",
    telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False},
)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
