"""Verify the built backend with developer runtimes removed from PATH."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import websockets


async def check_connection(process, port):
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError('Packaged backend exited before becoming ready')
        try:
            async with websockets.connect(f'ws://127.0.0.1:{port}', open_timeout=1) as ws:
                payload = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if payload.get('type') != 'game_data':
                    raise RuntimeError(f'Unexpected first packet: {payload.get("type")}')
                return
        except (OSError, TimeoutError):
            await asyncio.sleep(.25)
    raise RuntimeError('Packaged backend readiness timeout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, default=Path('dist-electron/win-unpacked/resources'))
    args = parser.parse_args()
    executable = args.resources.resolve() / 'backend/tft-coach-backend.exe'
    with tempfile.TemporaryDirectory(prefix='TFT Coach 한글 ') as directory:
        env = {**os.environ, 'TFT_COACH_USER_DATA': directory,
               'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
               'PYTHONIOENCODING': 'utf-8'}
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run([str(executable), '--self-test'], cwd=directory,
                                env=env, capture_output=True, timeout=60, creationflags=flags)
        print(result.stdout.decode('utf-8', errors='replace'))
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
        report = json.loads((Path(directory) / 'logs/self-test.json').read_text())
        assert report['frozen'] and report['ok'] and report['data'] == directory
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
        # Demo verifies the protocol without requiring a game to be open.
        process = subprocess.Popen([str(executable), '--demo', '--port', str(port)],
                                   cwd=directory, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            asyncio.run(check_connection(process, port))
        finally:
            process.terminate()
            process.wait(timeout=15)
        print('PASS: bundled OCR, ONNX inference, Unicode writable paths, demo WebSocket handshake')


if __name__ == '__main__':
    main()
