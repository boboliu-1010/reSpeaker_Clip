import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {readFileSync} from 'node:fs';
import {connectAt, grantedClip} from '../clip-config.mjs';
import { encodeCbor, decodeCbor, packet, SmpClient, FirmwareUpdater, connectSmp, disconnectGatt, hex, SMP_SERVICE, LEGACY_SMP_SERVICE } from '../smp.mjs';

test('reconnect only selects one previously authorized Clip and never requests permission', async () => {
  const clip = {name: 'Clip C7BB'};
  assert.equal(await grantedClip({getDevices: async () => [clip, {name: 'Headphones'}]}), clip);
  assert.equal(await grantedClip({getDevices: async () => [clip, {name: 'Clip Other'}]}), null);
  assert.equal(await grantedClip({}), null);
  assert.equal(await grantedClip({getDevices: async () => { throw Error('unavailable'); }}), null);
});

test('decode the physical Clip image-state response with indefinite maps and arrays', () => {
  const raw = Buffer.from(readFileSync(new URL('./fixtures/clip-0.1.2-201-image-state.cbor.txt', import.meta.url), 'utf8').trim(), 'hex');
  const result = decodeCbor(raw);
  assert.equal(result.images[0].active, true);
  assert.equal(result.images[0].confirmed, true);
  assert.equal(hex(result.images[0].hash), 'a8300aec4498e6e7d5c38fbce8b39b423eaec8d7646df0a4a7fdfbcbfb730135');
  assert.throws(() => decodeCbor(raw.subarray(0, -1)), /截断/);
  assert.throws(() => decodeCbor(Buffer.from('bf616101616102ff', 'hex')), /键无效/);
  assert.throws(() => decodeCbor(Buffer.from([0x9f,...new Array(129).fill(0),0xff])), /过大/);
  assert.throws(() => decodeCbor(Buffer.from([0xff])), /CBOR/);
});

for (const alreadyClosing of [false, true]) test(`SMP waits for old GATT disconnect (AT close already requested: ${alreadyClosing})`, async () => {
  const listeners = new Map(); let closing = false, notifications = false;
  const characteristic = {
    properties: {writeWithoutResponse: true},
    addEventListener() {}, removeEventListener() {},
    startNotifications: async () => { notifications = true; },
  };
  const server = {getPrimaryService: async () => ({getCharacteristic: async () => characteristic}), disconnect() {}};
  const device = {
    addEventListener: (name, cb) => listeners.set(name, cb),
    removeEventListener: (name, cb) => { if (listeners.get(name) === cb) listeners.delete(name); },
    gatt: {
      connected: true,
      disconnect() {
        closing = true;
        this.connected = false;
        setImmediate(() => { closing = false; this.connected = false; listeners.get('gattserverdisconnected')?.(); });
      },
      async connect() { assert.equal(closing, false, 'old link is still closing'); this.connected = true; return server; },
    },
  };
  const previous = alreadyClosing ? disconnectGatt(device) : null;
  const client = await connectSmp(device);
  if (previous) await previous;
  assert.equal(notifications, true);
  client.close();
});

test('real AT client close and SMP to AT handoff both await the old link', async () => {
  const events = new Map(); let closing = false, connects = 0;
  const characteristic = {
    properties: {writeWithoutResponse: true},
    addEventListener() {}, removeEventListener() {},
    startNotifications: async () => {}, writeValueWithoutResponse: async () => {},
  };
  const device = {
    addEventListener(name, cb) { if (!events.has(name)) events.set(name, new Set()); events.get(name).add(cb); },
    removeEventListener(name, cb) { events.get(name)?.delete(cb); },
    gatt: {
      connected: false,
      disconnect() {
        if (!this.connected) return;
        this.connected = false; closing = true;
        setImmediate(() => { closing = false; for (const cb of [...(events.get('gattserverdisconnected') || [])]) cb(); });
      },
      async connect() { assert.equal(closing, false); connects++; this.connected = true; return this; },
      async getPrimaryService() { assert.equal(this.connected, true); return {getCharacteristic: async () => characteristic}; },
    },
  };
  const at = await connectAt(device);
  at.close(); // Its real onClose hook starts asynchronous disconnection.
  const smp = await connectSmp(device);
  await disconnectGatt(device); // Same handoff used by page reselect/logout.
  const nextAt = await connectAt(device);
  assert.equal(connects, 3);
  const ended = disconnectGatt(device); nextAt.close(); await ended;
  smp.close();
});

test('AT to first SMP session reuses its GATT connection without disconnecting', async () => {
  let disconnects = 0;
  const characteristic = {properties: {writeWithoutResponse: true}, addEventListener() {},
    removeEventListener() {}, startNotifications: async () => {}, writeValueWithoutResponse: async () => {}};
  const device = {
    addEventListener() {}, removeEventListener() {},
    gatt: {connected: false,
      disconnect() { disconnects++; this.connected = false; },
      async connect() { this.connected = true; return this; },
      async getPrimaryService() { return {getCharacteristic: async () => characteristic}; },
    },
  };
  const at = await connectAt(device);
  at.close(undefined, false);
  assert.equal(disconnects, 0);
  const client = await connectSmp(device, {reuseConnection: true});
  assert.equal(disconnects, 0);
  assert.equal(device.gatt.connected, true);
  client.close();
});

test('connectSmp reads image state through the Zephyr service advertised by Clip', async () => {
  const seen = [], listeners = new Map();
  const characteristic = {
    properties: {writeWithoutResponse: true},
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener() {},
    startNotifications: async () => {},
    writeValueWithoutResponse: async bytes => {
      const reply = packet(1, 1, 0, bytes[6], {images: [{slot: 0, version: '0.1.2', active: true, confirmed: true}]});
      queueMicrotask(() => listeners.get('characteristicvaluechanged')({target: {value: new DataView(reply.buffer)}}));
    },
  };
  const device = {
    addEventListener() {}, removeEventListener() {},
    gatt: {connected: false, disconnect() {}, connect: async () => ({
      disconnect() {},
      getPrimaryService: async uuid => {
        seen.push(uuid);
        assert.equal(uuid, '8d53dc1d-1db7-4cd3-868b-8a527460aa84');
        return {getCharacteristic: async () => characteristic};
      },
    })},
  };
  const client = await connectSmp(device);
  assert.equal((await new FirmwareUpdater(client).images())[0].version, '0.1.2');
  assert.deepEqual(seen, ['8d53dc1d-1db7-4cd3-868b-8a527460aa84']);
  client.close();
});

for (const name of ['NotFoundError', 'SecurityError']) {
  test(`SMP service discovery only falls back on missing service (${name})`, async () => {
    const seen = [], listeners = new Map(); let disconnected = false;
    const characteristic = {
      properties: {writeWithoutResponse: true},
      addEventListener() {}, removeEventListener() {}, startNotifications: async () => {},
    };
    const error = Object.assign(Error('service lookup failed'), {name});
    const device = {
      addEventListener: (name, cb) => listeners.set(name, cb),
      removeEventListener: (name, cb) => { if (listeners.get(name) === cb) listeners.delete(name); },
      gatt: {connected: false,
        disconnect() { disconnected = true; this.connected = false; queueMicrotask(() => listeners.get('gattserverdisconnected')?.()); },
        connect: async () => { device.gatt.connected = true; return {
        getPrimaryService: async uuid => {
          seen.push(uuid);
          if (uuid === SMP_SERVICE) throw error;
          assert.equal(uuid, LEGACY_SMP_SERVICE);
          return {getCharacteristic: async () => characteristic};
        },
      }; }},
    };
    if (name === 'NotFoundError') {
      const client = await connectSmp(device);
      assert.deepEqual(seen, [SMP_SERVICE, LEGACY_SMP_SERVICE]);
      assert.equal(disconnected, false);
      client.close();
    } else {
      await assert.rejects(connectSmp(device), error);
      assert.deepEqual(seen, [SMP_SERVICE]);
      assert.equal(disconnected, true);
    }
  });
}

test('CBOR and SMP use published wire layout, including byte strings', () => {
  assert.equal(Buffer.from(encodeCbor({off: 0, data: new Uint8Array([1, 2])})).toString('hex'), 'a2636f6666006464617461420102');
  assert.equal(Buffer.from(packet(2, 1, 1, 7, {off: 0})).toString('hex'), '0200000600010701a1636f666600');
  assert.equal(decodeCbor(Uint8Array.from([0xa1, 0x62, 0x72, 0x63, 0x0a])).rc, 10);
  assert.throws(() => decodeCbor(Uint8Array.from([0x59, 0xff, 0xff])), /CBOR/);
});

test('SMP reassembles notifications and ignores a stale sequence', async () => {
  let client;
  client = new SmpClient(async bytes => {
    if (bytes.length < 8) return;
    const stale = packet(3, 1, 1, (bytes[6] + 1) % 256, {off: 5});
    client.receive(stale);
    const response = packet(3, 1, 1, bytes[6], {off: 128});
    client.receive(response.slice(0, 3)); client.receive(response.slice(3));
  }, 100);
  assert.equal((await client.request(2, 1, 1, {})).off, 128);
});

test('SMP surfaces busy and disconnect without a success result', async () => {
  let client;
  client = new SmpClient(async bytes => client.receive(packet(3, 1, 1, bytes[6], {rc: 10})), 100);
  await assert.rejects(client.request(2, 1, 1, {}), /busy/);
  client = new SmpClient(async () => client.close(), 100);
  await assert.rejects(client.request(0, 1, 0, {}), /断开/);
});

test('a timed-out partial write invalidates the transport and cannot affect a later request', async () => {
  let rejectWrite;
  const client = new SmpClient(() => new Promise((_, reject) => { rejectWrite = reject; }), 10);
  await assert.rejects(client.request(0, 1, 0, {}), /超时/);
  await assert.rejects(client.request(0, 1, 0, {}), /断开/);
  rejectWrite(Error('late failure from old write'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(client.closed, true);
});

const data = new Uint8Array(320).fill(42);
const target = '11'.repeat(32);
const expected = {sha256: createHash('sha256').update(data).digest('hex'), image_hash: target};
const image = (active, confirmed, hash = target) => ({image: 0, slot: active ? 0 : 1, active, confirmed, hash: Uint8Array.from(Buffer.from(hash, 'hex'))});

test('long SMP uploads refresh AT activity only between completed chunks', async () => {
  let time = 0, writing = false;
  const refreshed = [];
  const peer = {request: async (op, group, id, body) => {
    if (id === 1) { writing = true; time += 31000; writing = false; return {off: body.off + body.data.length}; }
    if (op === 0) return {images: [image(false, false)]};
    return {};
  }};
  const updater = new FirmwareUpdater(peer, () => time);
  await updater.upload(data, expected, () => {}, async () => {}, async () => {
    assert.equal(writing, false); refreshed.push(time);
  });
  assert.deepEqual(refreshed, [0, 31000, 62000, 93000]);
});

test('upload is only awaiting reconnect; active matching image is required before confirming', async () => {
  let uploaded = 0, confirming = false;
  const peer = {request: async (op, group, id, body) => {
    if (id === 1) { uploaded = body.off + body.data.length; return {off: uploaded}; }
    if (group === 0) return {};
    if (op === 2) { confirming = body.confirm; return {}; }
    return {images: [image(false, false)]};
  }};
  const updater = new FirmwareUpdater(peer);
  assert.deepEqual(await updater.upload(data, expected), {state: 'awaiting_reconnect'});
  assert.equal(uploaded, 320); assert.equal(confirming, false);
  await assert.rejects(updater.confirm(expected), /目标镜像/);
  peer.request = async (op, group, id, body) => {
    if (op === 2) { confirming = body.confirm; return {}; }
    return {images: [image(true, confirming)]};
  };
  const result = await updater.confirm(expected);
  assert.equal(result.confirmed, true); assert.equal(result.image_hash, target);
});

test('wrong file hash and non-progressing device offsets stop upgrade', async () => {
  const updater = new FirmwareUpdater({request: async () => ({off: 0})});
  await assert.rejects(updater.upload(data, {...expected, sha256: '00'.repeat(32)}), /文件哈希/);
  await assert.rejects(updater.upload(data, expected), /偏移/);
});
