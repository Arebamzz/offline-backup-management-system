#!/usr/bin/env node
const WebSocket = require('ws');

const url = process.env.URL || 'ws://localhost:8080/ws';
const args = process.argv.slice(2);
const msg = args[0] || null;
const level = args[1] || 'info';

function sendSample(ws){
  const samples = [
    {text:'Running script: pull_backup.py', level:'info'},
    {text:'Copying file: important.db -> backup/', level:'info'},
    {text:'Disk space low: /var at 95%', level:'warn'},
    {text:'Failed to copy file: critical.log', level:'error'}
  ];
  let i=0; const t=setInterval(()=>{
    if(i>=samples.length){ clearInterval(t); ws.close(); return }
    ws.send(JSON.stringify(samples[i++]));
  },800);
}

const ws = new WebSocket(url);
ws.on('open', ()=>{
  if(msg){ ws.send(JSON.stringify({text: msg, level})); ws.close(); return }
  sendSample(ws);
});
ws.on('close', ()=> process.exit(0));
ws.on('error', (e)=>{ console.error('ws error', e); process.exit(2) });
