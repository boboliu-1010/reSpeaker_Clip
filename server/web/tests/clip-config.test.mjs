import test from 'node:test';
import assert from 'node:assert/strict';
import {AtClient, JsonFramer, ClipConfigurator, wifiCommand, receiverCommand, decodeSsid} from '../clip-config.mjs';
import * as clip from '../clip-config.mjs';
const encoder = new TextEncoder();

test('configuration follows firmware CSV grammar and validates UTF-8 byte counts', () => {
  assert.equal(wifiCommand('办公室', 'pass,word'), 'AT+NETCFG=办公室,pass,word');
  assert.throws(() => wifiCommand('a,b', 'password'), /Wi-Fi/);
  assert.throws(() => wifiCommand('网'.repeat(11), 'password'), /Wi-Fi/);
  assert.throws(() => wifiCommand('ssid', 'password\nAT+RESET'), /Wi-Fi/);
  assert.equal(receiverCommand('100.58.19.213:9528', 'clip01', 'a'.repeat(40)), `AT+UPLOADCFG=100.58.19.213,9528,clip01,${'a'.repeat(40)}`);
  assert.throws(() => receiverCommand('https://host:9528', 'clip', 'a'.repeat(40)), /主机:端口/);
  assert.throws(() => receiverCommand('host:65536', 'clip', 'a'.repeat(40)), /主机:端口/);
  assert.throws(() => receiverCommand('host:9528', 'clip', 'bad\nvalue'), /设备令牌/);
  assert.equal(decodeSsid('e58a9ee585ace5aea4'), '办公室');
});

test('JSON framing handles escaped braces, concatenated objects and split UTF-8', () => {
  const bytes = encoder.encode('{"ok":true,"data":{"ssid":"网\\\"{点}"}}\n{"event":"upload","stage":"idle"}');
  const framer = new JsonFramer(); const rows = [];
  for (const byte of bytes) rows.push(...framer.push(Uint8Array.of(byte)));
  assert.equal(rows[0].data.ssid, '网"{点}'); assert.equal(rows[1].event, 'upload');
  assert.throws(() => new JsonFramer().push(encoder.encode('{"data":"' + 'a'.repeat(17000))), /响应过大/);
});

test('AT writes one whole command and ignores events and unrelated GSTAT replies', async () => {
  let client; let count = 0; const events = [];
  client = new AtClient(async bytes => {
    count++; assert.equal(new TextDecoder().decode(bytes), 'AT+NETCFG=office,password');
    client.receive(encoder.encode('{"event":"wifi_check","state":"checking"}{"ok":true,"data":{"state":"IDLE","recording":false}}'));
    const reply = encoder.encode('{"ok":true,"data":{"configured":true,"saved":true,"ssid_hex":"6f6666696365"}}');
    client.receive(reply.slice(0, 19)); client.receive(reply.slice(19));
  }, {timeout: 100, onEvent: event => events.push(event.event)});
  const reply = await client.send(wifiCommand('office', 'password'));
  assert.equal(reply.data.saved, true); assert.equal(count, 1); assert.deepEqual(events, ['wifi_check']);
});

test('oversized commands never reach BLE and errors never expose credentials', async () => {
  let writes = 0; let client;
  client = new AtClient(async () => { writes++; });
  await assert.rejects(client.send('AT+NETCFG=' + 'a'.repeat(255)), /255/);
  assert.equal(writes, 0);
  client = new AtClient(async () => { throw Error('raw secret password'); });
  await assert.rejects(client.send('AT+NETCFG=ssid,password'), error => !error.message.includes('password') && /单条写入/.test(error.message));
  assert.equal(client.closed, true);
});

test('AT timeout invalidates connection and late responses cannot settle another request', async () => {
  let invalidations = 0;
  const client = new AtClient(async () => {}, {timeout: 10, onClose: () => invalidations++});
  await assert.rejects(client.send('AT+VERSION'), /未确认/);
  assert.equal(invalidations, 1);
  client.receive(encoder.encode('{"ok":true,"firmware":"0.1.4"}'));
  await assert.rejects(client.send('AT+VERSION'), /重新连接/);
});

test('saving receiver disables automatic upload first and checks persistence without reading secrets', async () => {
  const commands = [];
  const client = {send: async command => {
    commands.push(command);
    if (command === 'AT+GSTAT') return {ok: true, data: {state:'IDLE', recording:false}};
    if (command === 'AT+UPLOADAUTO?') return {ok:true,data:{enabled:false}};
    if (command === 'AT+UPLOADCFG?') return {ok:true,data:{configured:true,saved:true}};
    return {ok:true,stage:'idle',active:false};
  }};
  const config = new ClipConfigurator(client);
  await config.saveReceiver('host:9528','clip','a'.repeat(40));
  assert.deepEqual(commands,['AT+GSTAT','AT+UPLOADAUTO=off','AT+UPLOADAUTO?',`AT+UPLOADCFG=host,9528,clip,${'a'.repeat(40)}`,'AT+UPLOADCFG?']);
});

test('busy or unpersisted configuration cannot be reported as saved', async () => {
  const busy = new ClipConfigurator({send: async () => ({ok:true,data:{state:'RECORDING',recording:true}})});
  await assert.rejects(busy.saveWifi('office','password'), /空闲/);
  const unpersisted = new ClipConfigurator({send: async command => command === 'AT+GSTAT' ? {ok:true,data:{state:'IDLE'}} : {ok:true,data:{saved:false}}});
  await assert.rejects(unpersisted.saveWifi('office','password'), /保存/);
});

test('network check is scoped to its job and Wi-Fi DHCP success is not Server validation', async () => {
  const updates = [];
  const client = {send: async command => command === 'AT+NETCHECK' ? {ok:true,data:{accepted:true,job:7,state:'checking',scope:'wifi_dhcp'}} : {ok:true,data:{job:7,state:'succeeded',scope:'wifi_dhcp',cleanup_error:0,ip:'192.168.1.3'}}};
  const result = await new ClipConfigurator(client).checkNetwork(row => updates.push(row.state), {interval:0,maxPolls:1});
  assert.equal(result.scope,'wifi_dhcp'); assert.deepEqual(updates,['checking','succeeded']);
  client.send = async command => command === 'AT+NETCHECK' ? {ok:true,data:{accepted:true,job:7}} : {ok:true,data:{job:8,state:'succeeded'}};
  await assert.rejects(new ClipConfigurator(client).checkNetwork(()=>{}, {interval:0,maxPolls:1}), /任务/);
});

test('a network success event received during the last read wins over an earlier checking snapshot', async () => {
  let client; const live = {};
  const replies = {
    'AT+VERSION': {ok:true,firmware:'0.1.5'},
    'AT+GSTAT': {ok:true,data:{state:'IDLE',recording:false}},
    'AT+NETCFG?': {ok:true,data:{configured:true,saved:true,ssid_hex:'6f'}},
    'AT+UPLOADCFG?': {ok:true,data:{configured:true,saved:true}},
    'AT+UPLOADAUTO?': {ok:true,data:{enabled:false}},
    'AT+NETCHECK?': {ok:true,data:{job:7,scope:'wifi_dhcp',state:'checking'}},
    'AT+UPLOAD?': {ok:true,data:{stage:'idle',active:false}}
  };
  client = new AtClient(async bytes => {
    const command = new TextDecoder().decode(bytes);
    if (command === 'AT+UPLOAD?') client.receive(encoder.encode('{"event":"wifi_check","job":7,"scope":"wifi_dhcp","state":"succeeded","cleanup_error":0}'));
    client.receive(encoder.encode(JSON.stringify(replies[command])));
  }, {onEvent: event => { live.network = event; }});
  const snapshot = await new ClipConfigurator(client).read();
  assert.equal(snapshot.network.state,'checking');
  assert.equal(clip.mergeClipSnapshot(snapshot,live).network.state,'succeeded');
});

test('save-and-check verifies stored SSID before starting a matching DHCP job', async () => {
  const commands=[];
  const client={send:async command=> {
    commands.push(command);
    if(command==='AT+GSTAT') return {ok:true,data:{state:'IDLE',recording:false}};
    if(command.startsWith('AT+NETCFG=')) return {ok:true,data:{saved:true,configured:true,ssid_hex:'6f6666696365'}};
    if(command==='AT+NETCHECK') return {ok:true,data:{accepted:true,job:8}};
    return {ok:true,data:{job:8,state:'succeeded',scope:'wifi_dhcp',cleanup_error:0,ip:'192.168.1.5'}};
  }};
  const result=await new ClipConfigurator(client).saveAndCheckWifi('office','password',()=>{}, {interval:0,maxPolls:1});
  assert.equal(result.network.ip,'192.168.1.5');
  assert.deepEqual(commands,['AT+GSTAT','AT+NETCFG=office,password','AT+NETCHECK','AT+NETCHECK?']);
  commands.length=0;
  await assert.rejects(new ClipConfigurator(client).saveAndCheckWifi('other','password',()=>{}, {interval:0,maxPolls:1}),/保存/);
  assert.equal(commands.includes('AT+NETCHECK'),false);
});
