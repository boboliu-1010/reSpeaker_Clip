// SMP v1 over BLE. Zephyr replies use indefinite CBOR maps and arrays.
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true});
const concat = (...parts) => Uint8Array.from(parts.flatMap(part => Array.from(part)));
export const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const unhex = value => Uint8Array.from(value.match(/../g), byte => parseInt(byte, 16));

export function encodeCbor(value) {
  function head(type, length) {
    if (!Number.isInteger(length) || length < 0 || length > 0xffffffff) throw Error('CBOR 数字越界');
    const base = type << 5;
    if (length < 24) return [base | length];
    if (length <= 255) return [base | 24, length];
    if (length <= 65535) return [base | 25, length >> 8, length & 255];
    return [base | 26, length >>> 24, (length >>> 16) & 255, (length >>> 8) & 255, length & 255];
  }
  if (value === false || value === true) return Uint8Array.of(value ? 0xf5 : 0xf4);
  if (Number.isInteger(value)) return Uint8Array.from(head(value < 0 ? 1 : 0, value < 0 ? -1 - value : value));
  if (value instanceof Uint8Array) return concat(head(2, value.length), value);
  if (typeof value === 'string') { const bytes = encoder.encode(value); return concat(head(3, bytes.length), bytes); }
  if (Array.isArray(value)) return concat(head(4, value.length), ...value.map(encodeCbor));
  if (value && typeof value === 'object') {
    const entries = Object.entries(value);
    return concat(head(5, entries.length), ...entries.flatMap(([key, item]) => [encodeCbor(key), encodeCbor(item)]));
  }
  throw Error('不支持的 CBOR 值');
}

export function decodeCbor(bytes) {
  let pos = 0;
  function take(count) {
    if (pos + count > bytes.length) throw Error('CBOR 数据截断');
    const result = bytes.slice(pos, pos + count); pos += count; return result;
  }
  function read(depth) {
    if (depth > 8) throw Error('CBOR 嵌套过深');
    const first = take(1)[0], major = first >> 5, extra = first & 31;
    if (first === 0xf4 || first === 0xf5) return first === 0xf5;
    if (first === 0xf6) return null;
    let length = extra;
    const indefinite = extra === 31 && (major === 4 || major === 5);
    if (extra >= 24 && !indefinite) {
      const count = {24: 1, 25: 2, 26: 4}[extra];
      if (!count) throw Error('不支持的 CBOR 长度');
      length = take(count).reduce((n, byte) => n * 256 + byte, 0);
    }
    if (major === 0) return length;
    if (major === 1) return -1 - length;
    if (major === 2) return take(length);
    if (major === 3) return decoder.decode(take(length));
    if (major === 4 || major === 5) {
      if (!indefinite && length > 128) throw Error('CBOR 容器过大');
      const result = major === 4 ? [] : Object.create(null);
      for (let i = 0; indefinite || i < length; i++) {
        if (indefinite && bytes[pos] === 0xff) { pos++; break; }
        if (i >= 128) throw Error('CBOR 容器过大');
        if (major === 4) result.push(read(depth + 1));
        else {
          const key = read(depth + 1);
          if (typeof key !== 'string' || Object.hasOwn(result, key)) throw Error('CBOR map 键无效');
          result[key] = read(depth + 1);
        }
      }
      return result;
    }
    throw Error('不支持的 CBOR 数据');
  }
  const result = read(0);
  if (pos !== bytes.length) throw Error('CBOR 尾部多余数据');
  return result;
}

export function packet(op, group, id, seq, body) {
  const payload = encodeCbor(body);
  if (payload.length > 65535) throw Error('SMP 请求过大');
  return concat([op, 0, payload.length >> 8, payload.length & 255, group >> 8, group & 255, seq, id], payload);
}

export class SmpClient {
  constructor(write, timeout = 12000) {
    this.write = write; this.timeout = timeout; this.seq = 0;
    this.buffer = new Uint8Array(); this.pending = null; this.closed = false;
  }
  close() {
    this.closed = true; this.pending?.reject(Error('蓝牙已断开，升级结果需要重新核实'));
    this.cleanup?.();
  }
  receive(bytes) {
    if (this.closed) return;
    this.buffer = concat(this.buffer, bytes);
    if (this.buffer.length > 65543) { this.closed = true; this.pending?.reject(Error('SMP 响应过大')); this.buffer = new Uint8Array(); return; }
    while (this.buffer.length >= 8) {
      const size = 8 + this.buffer[2] * 256 + this.buffer[3];
      if (this.buffer.length < size) return;
      const message = this.buffer.slice(0, size); this.buffer = this.buffer.slice(size);
      const pending = this.pending;
      if (!pending || message[6] !== pending.seq || message[7] !== pending.id ||
          message[4] * 256 + message[5] !== pending.group || (message[0] & 7) !== pending.op + 1) continue;
      try {
        const body = decodeCbor(message.slice(8));
        const error = body.err?.rc || body.rc;
        if (error) throw Error(error === 10 ? '设备返回 busy：正在执行其他任务，或当前固件未开放 DFU' : `设备拒绝请求（rc=${error}）`);
        pending.resolve(body);
      } catch (error) { pending.reject(error); }
    }
  }
  request(op, group, id, body) {
    if (this.closed) return Promise.reject(Error('蓝牙已断开'));
    if (this.pending) return Promise.reject(Error('已有 SMP 请求进行中'));
    const seq = this.seq++ % 256;
    const bytes = packet(op, group, id, seq, body);
    return new Promise((resolve, reject) => {
      const finish = (callback, value) => {
        if (this.pending !== job) return;
        clearTimeout(timer); this.pending = null; callback(value);
      };
      const job = {seq, op, group, id, resolve: value => finish(resolve, value), reject: error => finish(reject, error)};
      const timer = setTimeout(() => { this.closed = true; job.reject(Error('SMP 请求超时，请重连核实')); }, this.timeout);
      this.pending = job;
      Promise.resolve().then(async () => {
        for (let offset = 0; offset < bytes.length; offset += 20) {
          if (this.closed || this.pending !== job) break;
          await this.write(bytes.slice(offset, offset + 20));
        }
      }).catch(error => { if (this.pending === job) { this.closed = true; job.reject(error); } });
    });
  }
}

export const SMP_SERVICE = '8d53dc1d-1db7-4cd3-868b-8a527460aa84';
export const LEGACY_SMP_SERVICE = '00001530-1212-efde-1523-785feabcd123';
export const SMP_SERVICES = Object.freeze([SMP_SERVICE, LEGACY_SMP_SERVICE]);
export const SMP_CHARACTERISTIC = 'da2e7828-fbce-4e01-ae9e-261174997c48';

const disconnecting = new WeakMap();
export function disconnectGatt(device) {
  if (!device?.gatt) return Promise.resolve();
  const existing = disconnecting.get(device);
  if (existing) return existing;
  if (!device.gatt.connected) return Promise.resolve();
  let resolve, reject;
  const pending = new Promise((yes, no) => { resolve = yes; reject = no; });
  disconnecting.set(device, pending);
  const finish = error => {
    clearTimeout(timer);
    device.removeEventListener('gattserverdisconnected', ended);
    if (disconnecting.get(device) === pending) disconnecting.delete(device);
    error ? reject(error) : resolve();
  };
  const ended = () => finish();
  const timer = setTimeout(() => finish(Error('等待旧蓝牙连接关闭超时，请重新连接')), 5000);
  device.addEventListener('gattserverdisconnected', ended);
  try { device.gatt.disconnect(); } catch (error) { finish(error); }
  return pending;
}

export async function connectSmp(device, {reuseConnection = false} = {}) {
  // Never inherit a partial SMP packet or old listeners from a timed-out link.
  if (!reuseConnection) await disconnectGatt(device);
  else if (disconnecting.has(device)) await disconnecting.get(device);
  const server = await device.gatt.connect();
  try {
    let service;
    for (const uuid of SMP_SERVICES) {
      try { service = await server.getPrimaryService(uuid); break; }
      catch (error) { if (error.name !== 'NotFoundError') throw error; }
    }
    if (!service) throw Error('设备未提供受支持的 SMP 升级服务');
    const characteristic = await service.getCharacteristic(SMP_CHARACTERISTIC);
    const client = new SmpClient(bytes => characteristic.properties.writeWithoutResponse
      ? characteristic.writeValueWithoutResponse(bytes) : characteristic.writeValueWithResponse(bytes));
    const notification = event => {
      const value = event.target.value;
      client.receive(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
    };
    const disconnected = () => {
      client.close();
    };
    client.cleanup = () => {
      characteristic.removeEventListener('characteristicvaluechanged', notification);
      device.removeEventListener('gattserverdisconnected', disconnected);
    };
    characteristic.addEventListener('characteristicvaluechanged', notification);
    device.addEventListener('gattserverdisconnected', disconnected);
    try { await characteristic.startNotifications(); }
    catch (error) { disconnected(); throw error; }
    return client;
  } catch (error) { await disconnectGatt(device).catch(() => {}); throw error; }
}

export class FirmwareUpdater {
  constructor(client, now = () => Date.now()) { this.client = client; this.now = now; }
  async images() { return (await this.client.request(0, 1, 0, {})).images || []; }
  async upload(bytes, expected, progress = () => {}, awaiting = async () => {}, keepalive = async () => {}) {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    if (hex(digest) !== expected.sha256) throw Error('下载文件哈希不匹配');
    await keepalive();
    let lastActivity = this.now();
    const before = await this.images();
    if (before.some(image => image.pending)) throw Error('设备已有待启动镜像，请先处理');
    let offset = 0;
    while (offset < bytes.length) {
      const body = {off: offset, data: bytes.slice(offset, offset + 128)};
      if (offset === 0) Object.assign(body, {image: 0, len: bytes.length, sha: digest});
      const reply = await this.client.request(2, 1, 1, body);
      if (!Number.isInteger(reply.off) || reply.off <= offset || reply.off > bytes.length) throw Error('设备上传偏移无效或没有前进');
      offset = reply.off; progress(offset / bytes.length);
      // Clip's inactivity timer is refreshed by AT traffic. Query its version
      // at an SMP chunk boundary so no GATT operations race each other.
      if (this.now() - lastActivity >= 30000) {
        await keepalive(); lastActivity = this.now();
      }
    }
    const images = await this.images();
    if (!images.some(image => (image.image ?? 0) === 0 && image.slot === 1 && hex(image.hash || []) === expected.image_hash)) {
      throw Error('备用槽目标镜像哈希不匹配，未请求启动');
    }
    // Persist uncertainty before a test/reset command can change device state.
    await awaiting();
    await this.client.request(2, 1, 0, {hash: unhex(expected.image_hash), confirm: false});
    // Reset may sever BLE before its response. Neither case proves installation.
    try { await this.client.request(2, 0, 5, {}); } catch (_) { /* Must reconnect and inspect. */ }
    return {state: 'awaiting_reconnect'};
  }
  async confirm(expected) {
    const images = await this.images();
    if (!images.some(image => (image.image ?? 0) === 0 && image.slot === 0 && image.active && hex(image.hash || []) === expected.image_hash)) {
      throw Error('设备当前运行的不是目标镜像，不会发送确认命令');
    }
    await this.client.request(2, 1, 0, {hash: unhex(expected.image_hash), confirm: true});
    const after = await this.images();
    if (!after.some(image => (image.image ?? 0) === 0 && image.slot === 0 && image.active && image.confirmed && hex(image.hash || []) === expected.image_hash)) {
      throw Error('目标镜像尚未确认成功');
    }
    return {state: 'succeeded', active: true, confirmed: true, image_hash: expected.image_hash};
  }
}
