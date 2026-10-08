from fastapi import FastAPI

from app.api import admin, auth, documents

app = FastAPI(title="Plataforma de conhecimento interno")
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
