import test from 'node:test';
import assert from 'node:assert/strict';
import {AutomaticClipConfiguration} from '../device-configuration.mjs';
import {ClipConfigurator,AtClient} from '../clip-config.mjs';

const profile={device_id:'clip01',device_name:'Clip C7BB',owner:'alice',endpoint:'100.58.19.213:9528',device_token:'d'.repeat(40)};
function fake({enabled=false,active=false,recording=false,failSave=false,unknownSwitch=false}={}) {
  const sent=[];const client={send:async command=>{
    sent.push(command);
    if(command==='AT+DEVICE')return {ok:true,device:'Clip C7BB'};
    if(command==='AT+GSTAT')return {state:recording?'RECORDING':'IDLE',recording,battery:80};
    if(command==='AT+UPLOAD?')return {stage:'idle',active};
    if(command==='AT+UPLOADAUTO?')return unknownSwitch?{}:{enabled};
    if(command==='AT+UPLOADAUTO=off'){enabled=false;return {ok:true};}
    if(command==='AT+UPLOADAUTO=on'){enabled=true;return {ok:true};}
    if(command==='AT+UPLOADCFG?')return {saved:!failSave,configured:!failSave};
    if(command.startsWith('AT+UPLOADCFG='))return {ok:true};
    throw Error('Unexpected command '+command);
  }};
  return {client,sent,config:new ClipConfigurator(client)};
}
function args(config,extra={}) {return {config,owner:'alice',getProfile:async()=>({...profile}),isCurrent:()=>true,...extra};}

test('device name is recognized by real AT framing',async()=>{
  const client=new AtClient(async()=>{});const pending=client.send('AT+DEVICE');
  client.receive(new TextEncoder().encode('{"ok":true,"device":"Clip C7BB"}\n'));
  assert.equal((await pending).device,'Clip C7BB');
});
test('automatic setup reuses credential and does not repeat writes on refresh',async()=>{
  const {config,sent}=fake();const setup=new AutomaticClipConfiguration();
  const result=await setup.configure(args(config));
  assert.equal(result.device_id,'clip01');assert.ok(!('device_token' in result));
  assert.ok(sent.includes(`AT+UPLOADCFG=100.58.19.213,9528,clip01,${profile.device_token}`));
  const count=sent.length;await setup.configure(args(config));assert.equal(sent.length,count);
});
test('disabled switch stays disabled without enabling it',async()=>{
  const {config,sent}=fake({enabled:false});await new AutomaticClipConfiguration().configure(args(config));
  assert.ok(!sent.includes('AT+UPLOADAUTO=on'));
});
test('recording, active upload and unknown switch cause no target write',async()=>{
  for(const options of [{recording:true},{active:true},{unknownSwitch:true}]){
    const {config,sent}=fake(options);await assert.rejects(new AutomaticClipConfiguration().configure(args(config)));
    assert.ok(!sent.some(command=>command.startsWith('AT+UPLOADCFG=')));
    assert.ok(!sent.includes('AT+UPLOADAUTO=off'));
  }
});
test('stale identity after profile delivery cannot issue device writes',async()=>{
  const {config,sent}=fake();let current=true;
  await assert.rejects(new AutomaticClipConfiguration().configure(args(config,{isCurrent:()=>current,getProfile:async()=>{current=false;return {...profile};}})),{name:'AbortError'});
  assert.deepEqual(sent,['AT+DEVICE']);
});
test('owner mismatch, device mismatch or invalid configuration is rejected before writes',async()=>{
  for(const change of [{owner:'bob'},{device_name:'Clip other'},{device_token:'short'},{endpoint:'https://host'}]){
    const {config,sent}=fake();await assert.rejects(new AutomaticClipConfiguration().configure(args(config,{getProfile:async()=>({...profile,...change})})));
    assert.deepEqual(sent,['AT+DEVICE']);
  }
});
test('failed save does not enable upload or cache success, retry remains possible',async()=>{
  const {config,sent}=fake({failSave:true});const setup=new AutomaticClipConfiguration();
  await assert.rejects(setup.configure(args(config)));assert.ok(!sent.includes('AT+UPLOADAUTO=on'));
  const count=sent.length;await assert.rejects(setup.configure(args(config)));assert.ok(sent.length>count);
});
test('new login/connection retries and profile requests never store credentials',async()=>{
  const setup=new AutomaticClipConfiguration();const first=fake();await setup.configure(args(first.config));
  const second=fake();await setup.configure(args(second.config));assert.ok(second.sent.some(command=>command.startsWith('AT+UPLOADCFG=')));
});
test('retry after failed save never enables a disabled switch',async()=>{
  const {config,client,sent}=fake();const send=client.send;let first=true;
  client.send=async command=>{const reply=await send(command);if(command==='AT+UPLOADCFG?'&&first){first=false;return {configured:false,saved:false};}return reply;};
  const setup=new AutomaticClipConfiguration();await assert.rejects(setup.configure(args(config)));
  assert.ok(!sent.includes('AT+UPLOADAUTO=on'));
  await setup.configure(args(config));assert.ok(!sent.includes('AT+UPLOADAUTO=on'));
});
test('identity change while checking state cannot write target under an old login',async()=>{
  const {config,client,sent}=fake();const send=client.send;let current=true;
  client.send=async command=>{const reply=await send(command);if(command==='AT+UPLOADAUTO?')current=false;return reply;};
  await assert.rejects(new AutomaticClipConfiguration().configure(args(config,{isCurrent:()=>current})),{name:'AbortError'});
  assert.ok(!sent.some(command=>command.startsWith('AT+UPLOADCFG=')));
  assert.ok(!sent.includes('AT+UPLOADAUTO=on'));
});
test('enabled devices retain existing configuration without pausing their upload scheduler',async()=>{
  const {config,sent}=fake({enabled:true});
  const result=await new AutomaticClipConfiguration().configure(args(config));
  assert.equal(result.preserved,true);
  assert.ok(!sent.some(command=>command.includes('=')));
});
test('a refreshed Server configuration is checked even after successful setup',async()=>{
  const {config,sent}=fake();const setup=new AutomaticClipConfiguration();await setup.configure(args(config));
  await assert.rejects(setup.configure(args(config,{getProfile:async()=>{throw Error('revoked');}})),/revoked/);
  const count=sent.filter(c=>c.startsWith('AT+UPLOADCFG=')).length;
  await setup.configure(args(config,{getProfile:async()=>({...profile,endpoint:'new-host:9528'})}));
  assert.equal(sent.filter(c=>c.startsWith('AT+UPLOADCFG=')).length,count+1);
});
test('async session guard cancels writes if another tab changes login',async()=>{
  const {config,sent}=fake();let checks=0;
  await assert.rejects(new AutomaticClipConfiguration().configure(args(config,{isCurrent:async revalidate=>{if(revalidate)checks++;return !checks;}})),{name:'AbortError'});
  assert.ok(!sent.some(command=>command.includes('=')));
});
test('manual automatic-upload mutation checks async identity immediately before SET',async()=>{
  const sent=[];const config=new ClipConfigurator({send:async command=>{sent.push(command);return {saved:true,configured:true,enabled:true};}});
  await assert.rejects(config.automatic(true,async revalidate=>{if(revalidate)throw new DOMException('changed','AbortError');}),{name:'AbortError'});
  assert.deepEqual(sent,['AT+NETCFG?','AT+UPLOADCFG?']);
});
test('false identity result prevents SET as well as a thrown identity error',async()=>{
  const sent=[];const config=new ClipConfigurator({send:async command=>{sent.push(command);return {saved:true,configured:true,enabled:true};}});
  await assert.rejects(config.automatic(true,async()=>false),{name:'AbortError'});
  assert.deepEqual(sent,['AT+NETCFG?','AT+UPLOADCFG?']);
});
test('page has automatic status and retry without credential inputs',async()=>{
  const {readFile}=await import('node:fs/promises');const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
  assert.match(html,/id="receiver-status"/);assert.match(html,/id="configure-receiver"/);
  assert.doesNotMatch(html,/id="clip-(device-id|device-token|endpoint)"/);
});
