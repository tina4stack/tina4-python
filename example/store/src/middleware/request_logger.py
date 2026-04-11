import time
import logging

logger = logging.getLogger("store")


class RequestLogger:
    @staticmethod
    async def before(request, response):
        request._start_time = time.time()
        logger.info(f"--> {request.method} {request.url}")
        return request, response

    @staticmethod
    async def after(request, response):
        duration = (time.time() - getattr(request, "_start_time", time.time())) * 1000
        logger.info(f"<-- {request.method} {request.url} {response.status_code} {duration:.1f}ms")
        return request, response
