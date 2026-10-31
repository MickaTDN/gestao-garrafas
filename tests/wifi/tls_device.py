"""Disposable loopback TLS device adapter for the Chromium PWA test.

Chromium trusts the test server certificate. The upstream connection verifies
hostname/CA and presents the individual test-device certificate. TLS I/O belongs
to one event-loop thread; no trust-store changes or verification bypasses.
Native Android certificate selection/MDM remains a physical acceptance gate.
"""

import asyncio
import concurrent.futures
import ssl
import threading
from contextlib import contextmanager


@contextmanager
def tls_device(tls, hostname, port):
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.minimum_version = ssl.TLSVersion.TLSv1_2
    server_tls.load_cert_chain(tls / "server-chain.crt", tls / "server.key")
    device_tls = ssl.create_default_context(cafile=str(tls / "ca.crt"))
    device_tls.load_cert_chain(tls / "device.crt", tls / "device.key")
    ready = concurrent.futures.Future()

    async def serve():
        stop = asyncio.Event()
        handlers = set()

        async def handle(browser_reader, browser_writer):
            task = asyncio.current_task()
            handlers.add(task)
            upstream_writer = None
            relays = []

            async def copy(reader, writer):
                while block := await asyncio.wait_for(reader.read(65536), timeout=30):
                    writer.write(block)
                    await asyncio.wait_for(writer.drain(), timeout=30)

            try:
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        "127.0.0.1", port, ssl=device_tls, server_hostname=hostname
                    ),
                    timeout=20,
                )
                relays = [
                    asyncio.create_task(copy(browser_reader, upstream_writer)),
                    asyncio.create_task(copy(upstream_reader, browser_writer)),
                ]
                # TLS has no application-level half-close. Once one peer closes,
                # finish that relay and cancel the other before closing transports.
                await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
            except (OSError, TimeoutError):
                pass  # Browser cancellation; never logs request bodies.
            finally:
                for relay in relays:
                    relay.cancel()
                await asyncio.gather(*relays, return_exceptions=True)
                for writer in (browser_writer, upstream_writer):
                    if writer is not None:
                        writer.close()
                        try:
                            await asyncio.wait_for(writer.wait_closed(), timeout=2)
                        except (OSError, TimeoutError):
                            writer.transport.abort()
                handlers.discard(task)

        async with await asyncio.start_server(
            handle,
            "127.0.0.2",
            port,
            ssl=server_tls,
            ssl_handshake_timeout=30,
            ssl_shutdown_timeout=2,
        ) as server:
            ready.set_result((asyncio.get_running_loop(), stop))
            try:
                await stop.wait()
            finally:
                server.close()
                for handler in tuple(handlers):
                    handler.cancel()
                await asyncio.gather(*tuple(handlers), return_exceptions=True)

    def run():
        try:
            asyncio.run(serve())
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            else:
                # Preserve unexpected adapter failures without logging TLS data.
                failures.append(error)

    failures = []
    thread = threading.Thread(target=run, daemon=False)
    thread.start()
    try:
        loop, stop = ready.result(timeout=30)
        try:
            yield
        finally:
            loop.call_soon_threadsafe(stop.set)
    finally:
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Synthetic TLS adapter did not shut down")
    if failures:
        raise RuntimeError("Synthetic TLS adapter failed") from failures[0]
