import os
from django.utils.deprecation import MiddlewareMixin
import time


class DelayMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        super().__init__(get_response)
        self.extra_delay = int(os.environ.get("EXTRA_DELAY_REQUEST", "0"))

    def process_request(self, request):
        return None

    def process_response(self, request, response):
        time.sleep(self.extra_delay)
        return response
