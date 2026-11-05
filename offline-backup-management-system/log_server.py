#!/usr/bin/env python3
from aiohttp import web, WSMsgType
import aiofiles
import asyncio
import json
import os
from pathlib import Path

ROOT = Path('.').resolve()
MAX_LINES = 50

async def index(request):
    f = ROOT / 'activity_log.html'
    if not f.exists():
        return web.Response(text='activity_log.html not found', status=404)
    return web.FileResponse(f)

async def post_log(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(text='invalid json', status=400)
    # broadcast to websockets
    msg = json.dumps(data)
    for ws in request.app['sockets']:
        await ws.send_str(msg)
    # also save to a simple file for persistence
    await append_persist(data)
    return web.json_response({'ok': True})

async def append_persist(entry):
    p = ROOT / '.activity_log.json'
    logs = []
    if p.exists():
        try:
            async with aiofiles.open(p, 'r') as f:
                txt = await f.read()
                logs = json.loads(txt or '[]')
        except Exception:
            logs = []
    logs.append(entry)
    while len(logs) > MAX_LINES:
        logs.pop(0)
    async with aiofiles.open(p, 'w') as f:
        await f.write(json.dumps(logs))

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app['sockets'].add(ws)
    # send persisted logs on connect
    p = ROOT / '.activity_log.json'
    if p.exists():
        try:
            async with aiofiles.open(p, 'r') as f:
                txt = await f.read()
                for e in json.loads(txt or '[]'):
                    replay = dict(e)
                    replay['_persisted'] = True
                    await ws.send_str(json.dumps(replay))
        except Exception:
            pass
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            # echo/broadcast
            for other in request.app['sockets']:
                if other is not ws:
                    await other.send_str(msg.data)
        elif msg.type == WSMsgType.ERROR:
            print('ws error', ws.exception())
    request.app['sockets'].discard(ws)
    return ws

async def on_start(app):
    print('Starting Python log server, serving', ROOT)

def main():
    app = web.Application()
    app['sockets'] = set()
    app.router.add_get('/', index)
    app.router.add_get('/activity_log.html', index)
    app.router.add_post('/log', post_log)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_static('/', str(ROOT), show_index=False)
    app.on_startup.append(on_start)
    web.run_app(app, port=int(os.environ.get('PORT', 8080)))

if __name__ == '__main__':
    main()
