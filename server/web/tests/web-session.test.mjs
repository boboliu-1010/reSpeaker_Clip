import test from 'node:test';
import assert from 'node:assert/strict';
import {WebSession} from '../web-session.mjs';
test('ID login uses same-origin HttpOnly cookies without a credential file or token',async()=>{
  const requests=[];const session=new WebSession({fetcher:async(...args)=>{requests.push(args);return new Response('{"user_id":"bobo","role":"user"}');}});
  assert.equal((await session.login(' bobo ')).user_id,'bobo');
  assert.equal(requests[0][0],'/api/boa/v1/session');
  assert.equal(requests[0][1].credentials,'same-origin');
  assert.equal(requests[0][1].headers.Authorization,undefined);
  assert.deepEqual(JSON.parse(requests[0][1].body),{user_id:'bobo'});
});
test('restore handles no session; logout does not pretend an unavailable Server revoked it',async()=>{
  const session=new WebSession({fetcher:async()=>new Response('',{status:401})});
  assert.equal(await session.restore(),null);
  await assert.rejects(session.logout(),/401/);
});
test('invalid IDs and mismatched returned identities are rejected',async()=>{
  let count=0;const session=new WebSession({fetcher:async()=>{count++;return new Response('{"user_id":"other","role":"user"}');}});
  await assert.rejects(session.login('../alice'),/用户 ID/);assert.equal(count,0);
  await assert.rejects(session.login('alice'),/身份/);
});
