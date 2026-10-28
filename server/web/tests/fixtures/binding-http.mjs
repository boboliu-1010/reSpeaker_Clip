// Real HTTP + production JS modules; only the encrypted BLE byte transport is simulated.
import assert from 'node:assert/strict';
import {createInterface} from 'node:readline';
import {createHash} from 'node:crypto';
import {AtClient} from '../../clip-config.mjs';
import {ClipBindingConfigurator} from '../../clip-binding.mjs';
import {AutomaticClipBinding,BindingService} from '../../binding-configuration.mjs';

const input=createInterface({input:process.stdin,crlfDelay:Infinity})[Symbol.asyncIterator]();
const read=async()=>JSON.parse((await input.next()).value);
const report=value=>process.stdout.write(JSON.stringify(value)+'\n');

async function run(){
  const seed=await read();
  const base=new URL(seed.url);
  assert.equal(base.hostname,'127.0.0.1');
  const requestFor=token=>async(path,{method='GET',body}={})=>{
    const response=await fetch(new URL('/api/boa/v1'+path,base),{
      method,headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},
      body:body?JSON.stringify(body):undefined,
    });
    if(!response.ok){const error=Error('HTTP request rejected');error.status=response.status;throw error;}
    return response.json();
  };
  const request=requestFor(seed.alice),bob=requestFor(seed.bob);
  const service=new BindingService(request);
  const assigned=(await service.devices())[0];
  assert.equal(assigned.device_uid,seed.uid);
  assert.equal(assigned.provisioning_state,'assigned');
  assert.notEqual(assigned.last_received_at,null);
  assert.equal(assigned.last_upload_revision,null);
  assert.deepEqual((await new BindingService(bob).devices()),[]);
  await assert.rejects(bob('/devices/clip01/binding',{
    method:'POST',body:{device_uid:seed.uid},
  }),error=>error.status===404);

  const hardware={
    wifi:{ssid:'fixture-kept-wifi',password:'fixture-kept-password'},
    recordings:[{name:'existing-local.opus',bytes:8192}],
    automatic:true,
    receiver:{host:'old-target.invalid',port:9000,device:'old-device',credential:'old-fixture-credential'},
    binding:{device_uid:seed.uid,bound:false,saved:true,binding_id:'',epoch:0,revision:0},
  };
  const preserved={wifi:structuredClone(hardware.wifi),recordings:structuredClone(hardware.recordings)};
  let writeAttempts=0,successfulWrites=0,clears=0;
  const commands=[];
  let client;
  const dispatch=command=>{
    commands.push(command.split('=')[0]);
    if(command==='AT+IDENTITY?')return {device_uid:seed.uid,binding_protocol_version:1,model:'reSpeaker Clip'};
    if(command==='AT+BINDING?')return {...hardware.binding};
    if(command==='AT+GSTAT')return {state:'IDLE',recording:false,record_pending:false};
    if(command==='AT+UPLOAD?')return {stage:'idle',active:false};
    if(command==='AT+UPLOADAUTO?')return {enabled:hardware.automatic};
    if(command==='AT+UPLOADCFG?')return {configured:hardware.receiver!==null,saved:true};
    if(command.startsWith('AT+BINDCFG=')){
      if(++writeAttempts===1)return {error:-16};
      const [host,port,device,credential,bindingId,epoch,revision]=command.slice('AT+BINDCFG='.length).split(',');
      hardware.receiver={host,port:+port,device,credential};
      hardware.binding={device_uid:seed.uid,bound:true,saved:true,binding_id:bindingId,epoch:+epoch,revision:+revision};
      successfulWrites++;
      return {...hardware.binding};
    }
    if(command.startsWith('AT+BINDCLR=')){
      const [bindingId,revision]=command.slice('AT+BINDCLR='.length).split(',');
      assert.equal(bindingId,hardware.binding.binding_id);
      assert.equal(+revision,hardware.binding.revision);
      hardware.binding={device_uid:seed.uid,bound:false,saved:true,binding_id:'',epoch:0,revision:0};
      hardware.receiver=null;hardware.automatic=false;clears++;
      return {...hardware.binding,cleared_binding_id:bindingId};
    }
    throw Error('Unexpected BLE command');
  };
  client=new AtClient(async bytes=>{
    const result=dispatch(new TextDecoder().decode(bytes));
    const wire=new TextEncoder().encode(JSON.stringify(result.error?{ok:false,...result}:{ok:true,data:result})+'\n');
    // Exercise the real JSON framer across fragmented notifications.
    const split=Math.floor(wire.length/2);
    client.receive(wire.subarray(0,split));client.receive(wire.subarray(split));
  },{timeout:2000});
  const config=new ClipBindingConfigurator(client),automatic=new AutomaticClipBinding();
  const configure=()=>automatic.configure({config,owner:'alice',getProfile:identity=>service.profile(identity),
    confirm:profile=>service.confirm(profile),isCurrent:()=>true});
  await assert.rejects(configure(),{name:'ClipBusyError'});
  assert.equal(successfulWrites,0);
  assert.equal(hardware.receiver.host,'old-target.invalid');
  assert.equal(hardware.automatic,true);
  // Same bounded retry entry point as an idle retry; no off/on or legacy writes.
  const first=await configure();
  assert.equal(first.revision,1);
  assert.equal(hardware.receiver.host,'first-target.invalid');
  assert.equal(hardware.automatic,true);
  assert.deepEqual(hardware.wifi,preserved.wifi);
  assert.deepEqual(hardware.recordings,preserved.recordings);
  assert.equal('device_token' in first,false);
  assert.equal((await service.devices())[0].provisioning_state,'provisioned');
  await configure();
  assert.equal(successfulWrites,1);
  report({phase:'configured',revision:first.revision,busy_retries:1});

  assert.equal((await read()).phase,'reapply');
  const second=await configure();
  assert.equal(second.revision,2);
  assert.equal(hardware.receiver.host,'second-target.invalid');
  assert.equal(successfulWrites,2);
  assert.equal(hardware.automatic,true);
  assert.deepEqual(hardware.wifi,preserved.wifi);
  assert.deepEqual(hardware.recordings,preserved.recordings);
  const configured=(await service.devices())[0];
  assert.equal(configured.revision,2);
  assert.equal(configured.provisioning_state,'provisioned');
  assert.equal(configured.last_upload_revision,null);

  assert.deepEqual(await service.revoke('clip01'),{state:'revoked',device_cleanup_pending:true});
  const cleared=await config.clearBinding(second);
  assert.equal(cleared.bound,false);
  assert.equal(hardware.receiver,null);
  assert.equal(hardware.automatic,false);
  assert.equal(clears,1);
  assert.deepEqual(hardware.wifi,preserved.wifi);
  assert.deepEqual(hardware.recordings,preserved.recordings);
  assert.equal(commands.some(command=>['AT+UPLOADAUTO','AT+NETCFG','AT+UPLOADCFG','AT+FACTORY'].includes(command)),false);
  const revoked=(await service.devices())[0];
  assert.equal(revoked.provisioning_state,'revoked');
  assert.equal(revoked.device_cleanup_pending,true);
  const files=await request('/audio-files');
  assert.equal(files.items.length,1);
  const content=await fetch(new URL('/api/boa/v1/audio-files/'+files.items[0].id+'/content',base),{
    headers:{Authorization:'Bearer '+seed.alice},
  });
  assert.equal(content.status,200);
  const digest=createHash('sha256').update(Buffer.from(await content.arrayBuffer())).digest('hex');
  assert.equal(digest,seed.recording_sha256);
  assert.deepEqual(await bob('/audio-files'),{items:[]});
  client.close();
  report({phase:'done',revision:second.revision,successful_writes:successfulWrites,
    clear_verified:true,cleanup_pending:true,cloud_recording_hash_matches:true});
}
try{await run();process.exit(0);}
catch(error){process.stderr.write('Binding HTTP fixture failed ('+error.name+').\n');process.exit(1);}
