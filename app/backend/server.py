"""Local backend server for the VisoMaster Studio desktop app.

Protocol (127.0.0.1 only, every request carries the per-launch token):
- WebSocket /rpc  request {"id", "method", "params"} -> {"id", "result"} | {"id", "error"}
                  server events {"event", "data"}
- GET /img/<key>  encoded preview / face images

On start one line is written to stdout: `VISOMASTER_BACKEND {"port": N}`.
The process exits when stdin closes, so it never outlives the app.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hmac
import json
import os
import secrets
import sys
import threading
import traceback

# Must precede NumPy: OpenBLAS GEMV can deadlock against Torch/ONNX threads on macOS.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from aiohttp import WSMsgType, web  # noqa: E402

METHODS = {
    "app.hello": "hello",
    "app.schema": "schema",
    "app.startEngine": "start_engine",
    "workspace.state": "state",
    "settings.get": "get_settings",
    "settings.set": "set_settings",
    "models.list": "models",
    "models.download": "download_models",
    "models.cancel": "cancel_downloads",
    "models.import": "import_models",
    "media.add": "add_media",
    "media.list": "list_media",
    "media.remove": "remove_media",
    "media.select": "select_media",
    "faces.sources": "sources",
    "faces.targets": "targets",
    "faces.addSources": "add_sources",
    "faces.removeSource": "remove_source",
    "faces.detect": "detect_targets",
    "faces.removeTarget": "remove_target",
    "faces.assign": "assign",
    "params.get": "get_parameters",
    "params.set": "set_parameters",
    "params.reset": "reset_parameters",
    "params.copy": "copy_parameters",
    "view.set": "set_view",
    "preview.render": "preview",
    "export.start": "export",
    "export.all": "export_all",
    "live.start": "live_start",
    "live.stop": "live_stop",
    "live.status": "live_status",
    "live.detect": "live_detect",
    "issues.scan": "scan_issues",
    "issues.list": "issues",
    "project.new": "new_project",
    "project.save": "save_project",
    "project.open": "open_project",
    "markers.list": "markers",
    "markers.add": "add_marker",
    "markers.remove": "remove_marker",
    "segments.add": "add_segment",
    "segments.remove": "remove_segment",
    "segments.clear": "clear_segments",
    "presets.list": "presets",
    "presets.save": "save_preset",
    "presets.apply": "apply_preset",
    "presets.delete": "delete_preset",
    "embeddings.list": "embeddings",
    "embeddings.create": "create_embedding",
    "embeddings.remove": "remove_embedding",
    "embeddings.save": "save_embeddings",
    "embeddings.load": "load_embeddings",
    "embeddings.rename": "rename_embedding",
    "embeddings.order": "order_embeddings",
    "faces.applyReaging": "apply_reaging",
    "dfm.list": "dfm_models",
    "dfm.import": "import_dfm",
    "jobs.list": "list_jobs",
    "jobs.cancel": "cancel_job",
    "jobs.clear": "clear_jobs",
    "history.list": "history",
    "system.reveal": "reveal",
}


class Server:
    def __init__(self, token: str):
        from .service import Workspace

        self.token = token
        self.clients: set[web.WebSocketResponse] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="rpc")
        self.workspace = Workspace(self.emit)

    def authorised(self, request: web.Request) -> bool:
        supplied = request.query.get("token", "") or request.headers.get("X-Studio-Token", "")
        return hmac.compare_digest(supplied, self.token)

    def emit(self, event: str, data: dict) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(message)))

    async def _broadcast(self, message: str) -> None:
        for ws in list(self.clients):
            if ws.closed:
                self.clients.discard(ws)
                continue
            try:
                await ws.send_str(message)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    def call(self, method: str, params: dict | list | None):
        from .service import ApiError

        name = METHODS.get(method)
        if name is None:
            raise ApiError(f"未知方法 {method}", "method")
        target = getattr(self.workspace, name)
        if isinstance(params, list):
            return target(*params)
        return target(**(params or {}))

    async def rpc(self, request: web.Request) -> web.StreamResponse:
        if not self.authorised(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024, heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                asyncio.ensure_future(self._handle(ws, message.data))
        finally:
            self.clients.discard(ws)
        return ws

    async def _handle(self, ws: web.WebSocketResponse, raw: str) -> None:
        from .service import ApiError

        try:
            request = json.loads(raw)
            rid = request.get("id")
        except ValueError:
            return
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                self.pool, self.call, request.get("method", ""), request.get("params"))
            reply = {"id": rid, "result": result}
        except ApiError as exc:
            reply = {"id": rid, "error": {"message": str(exc), "code": exc.code}}
        except TypeError as exc:
            reply = {"id": rid, "error": {"message": f"请求参数错误：{exc}", "code": "params"}}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            reply = {"id": rid, "error": {"message": str(exc) or exc.__class__.__name__, "code": "internal"}}
        if not ws.closed:
            await ws.send_str(json.dumps(reply, ensure_ascii=False, default=str))

    async def image(self, request: web.Request) -> web.StreamResponse:
        if not self.authorised(request):
            raise web.HTTPForbidden()
        item = self.workspace.images.get(request.match_info["key"])
        if item is None:
            raise web.HTTPNotFound()
        mime, data = item
        return web.Response(body=data, content_type=mime, headers={"Cache-Control": "private, max-age=600"})

    async def live_stream(self, request: web.Request) -> web.StreamResponse:
        """MJPEG stream of the live session (multipart/x-mixed-replace)."""
        if not self.authorised(request):
            raise web.HTTPForbidden()
        live = self.workspace.live
        if live is None:
            raise web.HTTPNotFound()
        response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame",
                                               "Cache-Control": "no-store"})
        await response.prepare(request)
        loop = asyncio.get_running_loop()
        serial = -1
        try:
            while live.stats.running or live.serial != serial:
                serial, jpeg = await loop.run_in_executor(self.pool, live.wait_frame, serial)
                if not jpeg:
                    if not live.stats.running:
                        break
                    continue
                await response.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return response

    async def health(self, request: web.Request) -> web.StreamResponse:
        if not self.authorised(request):
            raise web.HTTPForbidden()
        return web.json_response({"ok": True})


def _watch_parent(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    try:
        while sys.stdin.read(1):
            pass
    except (OSError, ValueError):
        pass
    loop.call_soon_threadsafe(stop.set)


async def main_async(args, ready_stream) -> None:
    token = os.environ.get("VISOMASTER_BACKEND_TOKEN") or secrets.token_urlsafe(24)
    server = Server(token)
    server.loop = asyncio.get_running_loop()
    app = web.Application(client_max_size=16 * 1024 * 1024)
    app.router.add_get("/rpc", server.rpc)
    app.router.add_get("/img/{key}", server.image)
    app.router.add_get("/health", server.health)
    app.router.add_get("/live.mjpg", server.live_stream)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", args.port)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    ready = {"port": port}
    if not os.environ.get("VISOMASTER_BACKEND_TOKEN"):
        ready["token"] = token  # development only; the app always supplies its own token
    ready_stream.write("VISOMASTER_BACKEND " + json.dumps(ready) + "\n")
    ready_stream.flush()
    stop = asyncio.Event()
    if args.watch_stdin:
        threading.Thread(target=_watch_parent, args=(asyncio.get_running_loop(), stop), daemon=True).start()
    try:
        await stop.wait()
    finally:
        server.workspace.shutdown()
        await runner.cleanup()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="visomaster-backend")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-watch-stdin", dest="watch_stdin", action="store_false")
    args = parser.parse_args(argv)
    # Upstream modules print diagnostics; stdout carries only the ready line.
    ready_stream = sys.stdout
    sys.stdout = sys.stderr
    try:
        asyncio.run(main_async(args, ready_stream))
    except KeyboardInterrupt:
        pass
    os._exit(0)  # do not wait on daemon inference threads


if __name__ == "__main__":
    main()
