import test from 'node:test';
import assert from 'node:assert/strict';
import {AtClient} from '../clip-config.mjs';
import {ClipBindingConfigurator,bindingCommand} from '../clip-binding.mjs';
import {AutomaticClipBinding,BindingService} from '../binding-configuration.mjs';

const uid='1234567890abcdef';
const profile={device_uid:uid,device_id:'clip01',device_name:'Clip C7BB',owner_id:'alice',
  binding_id:'a'.repeat(32),epoch:1,revision:2,endpoint:'100.58.19.213:9528',device_token:'d'.repeat(43),state:'assigned'};
function fake({enabled=true,busy=false,failSave=false,current=null}={}) {
  const sent=[];let binding=current||{device_uid:uid,bound:false,saved:true,binding_id:'',epoch:0,revision:0};
  const client={send:async command=>{
    sent.push(command);
    if(command==='AT+IDENTITY?')return {device_uid:uid,binding_protocol_version:1,model:'reSpeaker Clip'};
    if(command==='AT+BINDING?')return {...binding};
    if(command==='AT+GSTAT')return {state:busy?'RECORDING':'IDLE',recording:busy};
    if(command==='AT+UPLOAD?')return {active:false};
    if(command==='AT+UPLOADAUTO?')return {enabled};
    if(command.startsWith('AT+BINDCFG=')){
      if(failSave)throw Error('persist failed');
      const parts=command.slice(11).split(',');
      binding={device_uid:uid,bound:true,saved:true,binding_id:parts[4],epoch:+parts[5],revision:+parts[6]};return {...binding};
    }
    if(command.startsWith('AT+BINDCLR=')){binding={device_uid:uid,bound:false,saved:true,binding_id:'',epoch:0,revision:0};enabled=false;return {...binding,cleared_binding_id:profile.binding_id};}
    throw Error('Unexpected command '+command);
  }};
  return {config:new ClipBindingConfigurator(client),client,sent};
}
const args=(config,extra={})=>({config,owner:'alice',getProfile:async()=>({...profile}),confirm:async()=>({state:'provisioned',binding_id:profile.binding_id,revision:profile.revision}),isCurrent:()=>true,...extra});

test('binding wire grammar rejects invalid revisions, credentials and oversized commands',()=>{
  assert.equal(bindingCommand(profile),`AT+BINDCFG=100.58.19.213,9528,clip01,${profile.device_token},${profile.binding_id},1,2`);
  for(const change of [{epoch:0},{revision:2**32},{binding_id:'invalid'},{device_token:'short'},{endpoint:'https://host'},{device_uid:'bad'}])assert.throws(()=>bindingCommand({...profile,...change}));
  assert.throws(()=>bindingCommand({...profile,endpoint:'x'.repeat(95)+':9528',device_id:'c'.repeat(32),device_token:'t'.repeat(96)}),/255/);
});
test('full UID and binding queries are parsed by the real AT transport',async()=>{
  for(const [command,data] of [['AT+IDENTITY?',{device_uid:uid,binding_protocol_version:1}],['AT+BINDING?',{device_uid:uid,bound:false,saved:true}]]){
    const client=new AtClient(async()=>{});const pending=client.send(command);client.receive(new TextEncoder().encode(JSON.stringify({ok:true,data})+'\n'));assert.deepEqual((await pending).data,data);
  }
});
test('unknown binding command is distinct from numeric busy and permission failures',async()=>{
  for(const [reply,name] of [[{ok:false,msg:'Unknown command'},'UnsupportedBindingError'],[{ok:false,error:-16},'ClipBusyError'],[{ok:false,error:-13},'Error']]){
    const client=new AtClient(async()=>{});const pending=client.send('AT+IDENTITY?');client.receive(new TextEncoder().encode(JSON.stringify(reply)));await assert.rejects(pending,{name});
  }
});
test('auto enabled old target is overwritten without toggling upload, wifi or storage commands',async()=>{
  const {config,sent}=fake({enabled:true,current:{device_uid:uid,bound:true,saved:true,binding_id:profile.binding_id,epoch:1,revision:1}});
  const saved=await config.saveBinding(profile);assert.equal(saved.revision,2);
  assert.equal(sent.filter(c=>c.includes('=')).length,1);assert.equal(sent.find(c=>c.includes('=')),bindingCommand(profile));
});
test('recording/active upload/busy admission cannot cause a configuration write',async()=>{
  const first=fake({busy:true});await assert.rejects(first.config.saveBinding(profile),{name:'ClipBusyError'});assert.ok(!first.sent.some(c=>c.includes('=')));
  const second=fake();const send=second.client.send;second.client.send=async c=>c==='AT+UPLOAD?'?{active:true}:send(c);await assert.rejects(second.config.saveBinding(profile),{name:'ClipBusyError'});assert.ok(!second.sent.some(c=>c.includes('=')));
});
test('other binding, newer device revision and UID mismatch do not overwrite',async()=>{
  for(const current of [{binding_id:'b'.repeat(32),revision:1},{binding_id:profile.binding_id,revision:3},{binding_id:profile.binding_id,revision:1,epoch:2}]){
    const {config,sent}=fake({current:{device_uid:uid,bound:true,saved:true,epoch:1,...current}});await assert.rejects(config.saveBinding(profile));assert.ok(!sent.some(c=>c.includes('=')));
  }
  const {config,sent}=fake();await assert.rejects(config.saveBinding({...profile,device_uid:'f'.repeat(16)}));assert.ok(!sent.some(c=>c.includes('=')));
});
test('readback mismatch or save failure never confirms success',async()=>{
  const failed=fake({failSave:true});await assert.rejects(failed.config.saveBinding(profile),/persist/);
  const other=fake();const send=other.client.send;let writes=0;other.client.send=async c=>{const reply=await send(c);if(c.startsWith('AT+BINDCFG='))writes++;if(c==='AT+BINDING?'&&writes)return {...reply,revision:1};return reply;};await assert.rejects(other.config.saveBinding(profile),/确认/);
});
test('identity cancellation immediately before atomic SET prevents mutation',async()=>{
  const {config,sent}=fake();await assert.rejects(config.saveBinding(profile,async mutate=>mutate?false:true),{name:'AbortError'});assert.ok(!sent.some(c=>c.includes('=')));
});
test('coordinator fetches owned UID profile, verifies save then confirms client evidence',async()=>{
  const {config,sent}=fake();let confirmed=0;const setup=new AutomaticClipBinding();
  const result=await setup.configure(args(config,{confirm:async p=>{confirmed++;assert.equal(p.device_uid,uid);return {state:'provisioned',binding_id:p.binding_id,revision:p.revision};}}));
  assert.equal(confirmed,1);assert.equal(result.owner_id,'alice');assert.ok(!('device_token' in result));
  const writes=sent.filter(c=>c.startsWith('AT+BINDCFG=')).length;await setup.configure(args(config));assert.equal(sent.filter(c=>c.startsWith('AT+BINDCFG=')).length,writes);
});
test('UID can be displayed for developer enrollment without exposing credentials',async()=>{
  const {config}=fake();let shown;
  await new AutomaticClipBinding().configure(args(config,{onIdentity:value=>shown=value}));
  assert.equal(shown.device_uid,uid);assert.ok(!('device_token' in shown));
});
test('Server profile change while acquiring write admission prevents stale SET',async()=>{
  const {config,sent}=fake();let reads=0;
  await assert.rejects(new AutomaticClipBinding().configure(args(config,{getProfile:async()=>({...profile,revision:++reads===1?2:3})})),{name:'ConfigurationChangedError'});
  assert.ok(!sent.some(c=>c.includes('=')));
});
test('wrong-owner Server response and failed confirm are never cached as success',async()=>{
  const first=fake();await assert.rejects(new AutomaticClipBinding().configure(args(first.config,{getProfile:async()=>({...profile,owner_id:'bob'})})));assert.ok(!first.sent.some(c=>c.includes('=')));
  const second=fake();await assert.rejects(new AutomaticClipBinding().configure(args(second.config,{confirm:async()=>{throw Error('confirm failed');}})),/confirm failed/);
});
test('binding service looks up current user devices by UID, never by display name',async()=>{
  const calls=[];const service=new BindingService(async(path,options={})=>{
    calls.push([path,options]);
    if(path==='/devices')return {items:[{device_id:'clip-other',device_uid:'f'.repeat(16),device_name:'Clip C7BB'},{device_id:'clip01',device_uid:uid,device_name:'renamed'}]};
    return {...profile};
  });
  assert.equal((await service.profile({device_uid:uid})).device_id,'clip01');assert.equal(calls[1][0],'/devices/clip01/binding');assert.deepEqual(calls[1][1].body,{device_uid:uid});
  await assert.rejects(new BindingService(async()=>({items:[]})).profile({device_uid:uid}),/登记/);
});
test('explicit clear checks binding and leaves Wi-Fi and recordings untouched',async()=>{
  const {config,sent}=fake({current:{device_uid:uid,bound:true,saved:true,binding_id:profile.binding_id,epoch:1,revision:2}});
  const result=await config.clearBinding(profile);assert.equal(result.bound,false);
  assert.deepEqual(sent.filter(c=>c.includes('=')),[`AT+BINDCLR=${profile.binding_id},2`]);
});
test('empty binding metadata does not prove old receiver credentials were cleared',async()=>{
  const {config,client,sent}=fake();const send=client.send;
  client.send=async c=>c==='AT+UPLOADCFG?'?{saved:true,configured:true}:send(c);
  await assert.rejects(config.clearBinding(profile),/凭证/);
  assert.ok(!sent.some(c=>c.includes('=')));
});
test('only unsupported IDENTITY allows legacy fallback, never a partial new protocol',async()=>{
  const first=fake();first.config.identity=async()=>{const e=Error('old');e.name='UnsupportedBindingError';throw e;};
  await assert.rejects(new AutomaticClipBinding().configure(args(first.config)),e=>e.name==='UnsupportedBindingError'&&e.legacyAllowed===true);
  const second=fake();second.config.saveBinding=async()=>{const e=Error('partial');e.name='UnsupportedBindingError';throw e;};
  await assert.rejects(new AutomaticClipBinding().configure(args(second.config)),e=>e.name==='UnsupportedBindingError'&&!e.legacyAllowed);
});
