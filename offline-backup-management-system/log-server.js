#!/usr/bin/env node
const http = require('http');
const fs = require('fs');
const path = require('path');
const { WebSocketServer } = require('ws');

const PORT = process.env.PORT || 8080;
const PUBLIC_DIR = process.cwd();

function contentType(file){
  const ext = path.extname(file).toLowerCase();
  return ({'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.jpg':'image/jpeg'})[ext] || 'text/plain';
}

const server = http.createServer((req,res)=>{
  if(req.method === 'POST' && req.url === '/log'){
    let body = '';
    req.on('data',c=>body+=c);
    req.on('end',()=>{
      try{
        const obj = JSON.parse(body);
        broadcast(JSON.stringify(obj));
        res.writeHead(200,{'content-type':'application/json'});
        res.end(JSON.stringify({ok:true}));
      }catch(e){ res.writeHead(400); res.end('invalid json') }
    });
    return;
  }

  // serve static files
  let filePath = decodeURIComponent(req.url.split('?')[0]);
  if(filePath === '/' ) filePath = '/activity_log.html';
  const full = path.join(PUBLIC_DIR, filePath);
  fs.readFile(full, (err,data)=>{
    if(err){ res.writeHead(404); res.end('Not found'); return }
    res.writeHead(200,{'Content-Type': contentType(full)});
    res.end(data);
  });
});

const wss = new WebSocketServer({ server, path: '/ws' });
function broadcast(msg, origin){
  wss.clients.forEach(c=>{ if(c.readyState===1 && c !== origin) c.send(msg) });
}

wss.on('connection', (ws, req)=>{
  console.log('ws connected', req.socket.remoteAddress);
  ws.on('message', (m)=>{
    try{ const s = m.toString(); console.log('recv:', s); broadcast(s, ws); }
    catch(e){ console.error('ws msg err', e) }
  });
  ws.on('close', ()=> console.log('ws closed'));
});

server.listen(PORT, ()=> console.log('Log server running on http://localhost:'+PORT));
