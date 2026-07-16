import time
from fastapi import FastAPI, Request, Response
import structlog
from app.config import settings
from app.logging_config import setup_logging

# Setup structured logging
setup_logging()
logger = structlog.get_logger()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Radar — News Aggregator & Analyzer Bot",
    version="1.0.0"
)

@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    structlog.contextvars.clear_contextvars()
    start_time = time.perf_counter()
    
    response = await call_next(request)
    
    process_time = time.perf_counter() - start_time
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(process_time * 1000, 2)
    )
    return response

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "timestamp": time.time()
    }
