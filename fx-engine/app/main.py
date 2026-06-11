"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Return application health status."""
    return {"status": "ok"}
