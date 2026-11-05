#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from aiohttp import ClientSession, WSMsgType

URL = os.environ.get('URL', 'http://localhost:8080')

async def send_once(text, level='info'):
    async with ClientSession() as sess:
        payload = {'text': text, 'level': level}
        async with sess.post(URL + '/log', json=payload) as resp:
            print('sent', resp.status)

async def sample_sequence():
    samples = [
        {'text':'Running script: pull_backup.py', 'level':'info'},
        {'text':'Copying file: important.db -> backup/', 'level':'info'},
        {'text':'Disk space low: /mnt at 95%', 'level':'warn'},
        {'text':'Failed to copy file: critical.log', 'level':'error'}
    ]
    async with ClientSession() as sess:
        for s in samples:
            async with sess.post(URL + '/log', json=s) as resp:
                print('sent', s['text'], resp.status)
            await asyncio.sleep(0.8)

def main():
    if len(sys.argv) > 1:
        text = sys.argv[1]
        level = sys.argv[2] if len(sys.argv) > 2 else 'info'
        asyncio.run(send_once(text, level))
    else:
        asyncio.run(sample_sequence())

if __name__ == '__main__':
    main()
