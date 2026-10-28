import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {sortRecordings,contentPath,loadRecording,PlaybackRequests} from '../recordings.mjs';
const bytes=Uint8Array.of(3,0,0xf8,11,22);
const row={id:'a'.repeat(32),sha256:createHash('sha256').update(bytes).digest('hex'),size:bytes.length,source:'clip_direct',mime:'application/octet-stream'};
test('cookie playback uses same-origin credentials without an Authorization header',async()=>{
  let options;
  await loadRecording(row,{token:'',cookieSession:true,userId:'alice',fetcher:async(_path,request)=>{options=request;return new Response(bytes);}});
  assert.equal(options.credentials,'same-origin');assert.equal(options.headers.Authorization,undefined);
  assert.equal(options.headers['X-Boa-User'],'alice');
  await assert.rejects(loadRecording(row,{token:''}),/登录/);
});
test('time is descending with deterministic descending IDs on ties',()=>{
  const rows=[{id:'a',created:3},{id:'b',created:4},{id:'c',created:4}];
  assert.deepEqual(sortRecordings(rows).map(x=>x.id),['c','b','a']);assert.equal(rows[0].id,'a');
});
test('content routes distinguish actual Clip and App storage and reject path injection',()=>{
  assert.equal(contentPath(row),`/api/boa/v1/audio-files/${row.id}/content`);
  assert.equal(contentPath({...row,source:'app_upload'}),`/api/audio/recordings/${row.id}/content`);
  assert.throws(()=>contentPath({...row,id:'../secrets'}));
  assert.throws(()=>contentPath({...row,source:'other'}));
});
test('protected fetch authenticates with a header, verifies the original, then wraps Clip audio',async()=>{
  let requested;
  const audio=await loadRecording(row,{token:'private-token',fetcher:async(path,options)=>{
    requested={path,options};return new Response(bytes,{headers:{'Content-Length':String(bytes.length)}});
  }});
  assert.equal(requested.options.headers.Authorization,'Bearer private-token');
  assert.equal(requested.options.redirect,'error');assert.equal(requested.options.cache,'no-store');
  assert.ok(!requested.path.includes('private-token'));assert.equal(audio.mime,'audio/ogg');assert.equal(audio.duration,.02);
  assert.equal(new TextDecoder().decode(audio.bytes.subarray(0,4)),'OggS');
});
test('wrong hash, truncated response, surplus bytes and forbidden request fail closed',async()=>{
  await assert.rejects(loadRecording({...row,sha256:'0'.repeat(64)},{token:'x',fetcher:async()=>new Response(bytes)}),/SHA-256/);
  for(const body of [bytes.slice(0,-1),Uint8Array.from([...bytes,1])])
    await assert.rejects(loadRecording(row,{token:'x',fetcher:async()=>new Response(body)}),/长度/);
  await assert.rejects(loadRecording(row,{token:'x',fetcher:async()=>new Response('',{status:403})}),/403/);
});
test('oversized and malformed metadata never send a request',async()=>{
  let calls=0;const fetcher=async()=>{calls++;return new Response(bytes);};
  for(const invalid of [{...row,size:8*1024*1024+1},{...row,sha256:'bad'},{...row,size:-1}])
    await assert.rejects(loadRecording(invalid,{token:'x',fetcher}));
  assert.equal(calls,0);
});
test('standard audio retains its format and has a 64 MiB in-memory limit',async()=>{
  const audio=await loadRecording({...row,source:'app_upload',mime:'audio/wav'},{token:'x',fetcher:async()=>new Response(bytes)});
  assert.deepEqual(audio.bytes,bytes);assert.equal(audio.mime,'audio/wav');
  await assert.rejects(loadRecording({...row,source:'app_upload',size:64*1024*1024+1},{token:'x'}),/64 MiB/);
});
test('switching tracks cancels the old load even if its loader ignores abort',async()=>{
  const pending=[];const requests=new PlaybackRequests((r,options)=>new Promise(resolve=>pending.push({r,options,resolve})));
  const first=requests.load(row,{token:'alice'});const stale=assert.rejects(first,{name:'AbortError'});
  const second=requests.load({...row,id:'b'.repeat(32)},{token:'alice'});
  assert.equal(pending[0].options.signal.aborted,true);
  pending[1].resolve({bytes:Uint8Array.of(2)});assert.deepEqual((await second).bytes,Uint8Array.of(2));
  pending[0].resolve({bytes:Uint8Array.of(1)});await stale;
});
test('logout invalidates an in-flight request before another account can receive it',async()=>{
  let resolve;const requests=new PlaybackRequests(()=>new Promise(r=>resolve=r));
  const old=requests.load(row,{token:'alice'});const stale=assert.rejects(old,{name:'AbortError'});
  requests.reset();resolve({bytes:Uint8Array.of(1)});await stale;
});
test('an old account failure cannot invalidate a newer playback request',async()=>{
  const jobs=[];const requests=new PlaybackRequests(()=>new Promise((resolve,reject)=>jobs.push({resolve,reject})));
  const first=requests.load(row,{token:'',cookieSession:true,userId:'alice'});const stale=assert.rejects(first,{name:'AbortError'});
  const next=requests.load(row,{token:'',cookieSession:true,userId:'bob'});
  jobs[1].resolve({bytes});await next;
  const error=Error('old account changed');error.name='SessionChangedError';jobs[0].reject(error);await stale;
});
