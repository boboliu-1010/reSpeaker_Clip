import test from 'node:test';
import assert from 'node:assert/strict';
import {ServerConnection} from '../server-connection.mjs';
const healthy=()=>new Response(JSON.stringify({service:'boa',status:'ok'}),{headers:{'Content-Type':'application/json'}});
test('calls native fetch without binding it to the connection model',async()=>{
  const link=new ServerConnection({fetcher:async function(){assert.equal(this,undefined);return healthy();}});
  assert.equal(await link.connect(),'online');
});
test('checks the same Server without user credentials',async()=>{
  let requested;const seen=[];
  const link=new ServerConnection({fetcher:async(...args)=>{requested=args;return healthy();},onChange:s=>seen.push(s)});
  assert.equal(await link.connect(),'online');
  assert.equal(requested[0],'/api/boa/v1/health');
  assert.equal(requested[1].credentials,'omit');assert.equal(requested[1].redirect,'error');
  assert.equal(requested[1].cache,'no-store');assert.equal(requested[1].headers,undefined);
  assert.deepEqual(seen,['connecting','online']);
});
test('HTTP errors, unrelated JSON and invalid bodies cannot claim Server connected',async()=>{
  for(const response of [new Response('',{status:503}),new Response('{"status":"ok"}'),new Response('<html>proxy login</html>')]){
    const link=new ServerConnection({fetcher:async()=>response});assert.equal(await link.connect(),'offline');
  }
});
test('timeout aborts the request even if transport ignores cancellation',async()=>{
  let signal;const link=new ServerConnection({timeoutMs:5,fetcher:(_url,options)=>{signal=options.signal;return new Promise(()=>{});}});
  assert.equal(await link.connect(),'offline');assert.equal(signal.aborted,true);
});
test('successful login cannot be overwritten by an earlier failed health request',async()=>{
  let reject;const link=new ServerConnection({fetcher:()=>new Promise((_,r)=>reject=r)});
  const pending=link.connect();link.confirm();reject(Error('old network failure'));await pending;
  assert.equal(link.status,'online');
});
test('a newer retry wins over a stale response',async()=>{
  const pending=[];const link=new ServerConnection({fetcher:()=>new Promise(resolve=>pending.push(resolve))});
  const old=link.connect(),fresh=link.connect();pending[1](healthy());await fresh;
  pending[0](new Response('',{status:503}));await old;assert.equal(link.status,'online');
});
