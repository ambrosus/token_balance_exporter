from aiohttp import web
from prometheus_client import generate_latest
import logging

logger = logging.getLogger(__name__)

async def create_web_app(monitor):
    app = web.Application()
    app.router.add_get("/health", monitor.health_check_handler)
    app.router.add_get("/metrics", metrics_handler)
    return app

async def metrics_handler(request):
    metrics_data = generate_latest()
    return web.Response(
        body=metrics_data,
        content_type='text/plain; version=0.0.4'
    )
