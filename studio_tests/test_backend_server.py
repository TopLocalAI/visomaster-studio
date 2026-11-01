"""Backend process: token, ready line, error reporting and shutdown with no models installed."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]


def test_server_protocol(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"model_dir": str(tmp_path / "models"), "output_dir": str(tmp_path / "out")}))
    env = dict(os.environ, VISOMASTER_STUDIO_HOME=str(tmp_path), VISOMASTER_BACKEND_TOKEN="secret-token")
    proc = subprocess.Popen([sys.executable, "studio_backend.py"], cwd=ROOT, env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        line = proc.stdout.readline()
        assert line.startswith("VISOMASTER_BACKEND ")
        ready = json.loads(line.split(" ", 1)[1])
        assert "token" not in ready  # the app supplied the token; never echoed
        port = ready["port"]

        async def run():
            async with aiohttp.ClientSession() as http:
                assert (await http.get(f"http://127.0.0.1:{port}/health")).status == 403
                assert (await http.get(f"http://127.0.0.1:{port}/health?token=wrong")).status == 403
                ws = await http.ws_connect(f"http://127.0.0.1:{port}/rpc?token=secret-token")

                async def call(i, method, **params):
                    await ws.send_str(json.dumps({"id": i, "method": method, "params": params}))
                    while True:
                        msg = json.loads((await ws.receive()).data)
                        if msg.get("id") == i:
                            return msg

                hello = (await call(1, "app.hello"))["result"]
                assert hello["base_models_ready"] is False
                assert (await call(2, "app.startEngine"))["error"]["code"] == "models_missing"
                assert (await call(3, "no.such"))["error"]["code"] == "method"
                assert "error" in await call(4, "media.add", paths=[str(tmp_path / "missing.png")])
                models = (await call(5, "models.list"))["result"]
                assert len(models["items"]) == 78 and all(m["state"] == "missing" for m in models["items"])
                await ws.close()

        asyncio.run(run())
    finally:
        proc.stdin.close()  # closing stdin is the shutdown signal
        assert proc.wait(timeout=20) == 0
