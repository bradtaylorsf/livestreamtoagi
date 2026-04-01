from fastapi import FastAPI

app = FastAPI(title="Livestream AGI", version="0.1.0")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
