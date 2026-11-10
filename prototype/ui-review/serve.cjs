'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = __dirname;
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.woff2':'font/woff2','.txt':'text/plain; charset=utf-8'};
http.createServer((request,response)=>{
  let pathname;
  try { pathname = decodeURIComponent(new URL(request.url,'http://127.0.0.1').pathname); }
  catch { response.writeHead(400); response.end('Bad request'); return; }
  const file = path.resolve(root,`.${pathname==='/'?'/index.html':pathname}`);
  if (!file.startsWith(root+path.sep) || !types[path.extname(file)]) {response.writeHead(404);response.end('Not found');return;}
  fs.readFile(file,(error,content)=>{if(error){response.writeHead(404);response.end('Not found');return;}response.writeHead(200,{'Content-Type':types[path.extname(file)],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"});response.end(content);});
}).listen(4173,'127.0.0.1',()=>console.log('UI review: http://127.0.0.1:4173/ (Ctrl+C to stop)'));
