import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
const args=process.argv.slice(2),arg=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const host=arg('--host','127.0.0.1'),port=Number(arg('--port','4173'));
const root=path.resolve('dist');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpeg':'image/jpeg','.jpg':'image/jpeg','.pdf':'application/pdf','.ttf':'font/ttf'};
const server=http.createServer(async(req,res)=>{
  try{
    let pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(pathname.startsWith('/bronepehota/'))pathname=pathname.slice('/bronepehota'.length);
    if(pathname.endsWith('/'))pathname+='index.html';
    const file=path.resolve(root,'.'+pathname);
    if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
    const data=await fs.readFile(file);
    res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'});res.end(data);
  }catch{res.writeHead(404,{'Content-Type':'text/html; charset=utf-8'});res.end(await fs.readFile(path.join(root,'404.html')));}
});
server.listen(port,host,()=>console.log(`Preview: http://${host}:${port}/`));
