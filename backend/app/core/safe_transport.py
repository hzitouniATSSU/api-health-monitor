
import httpcore
import httpx

from app.core.safe_network import SafeNetworkBackend


class SafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(
            verify=True,
            trust_env=False,
            http1=True,
            http2=False,
            retries=0,
        )

        original_pool = self._pool

        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=original_pool._ssl_context,
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=SafeNetworkBackend(),
        )
