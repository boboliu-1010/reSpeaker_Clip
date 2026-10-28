// Existing Clip AT protocol over its encrypted Nordic-UART-like service.
import {disconnectGatt} from './smp.mjs';
export const AT_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
export async function grantedClip(bluetooth) {
  if (typeof bluetooth?.getDevices !== 'function') return null;
  try {
    const devices = (await bluetooth.getDevices()).filter(device => /^(Clip|CLIP|reSpeaker)/.test(device.name || ''));
    return devices.length === 1 ? devices[0] : null;
  } catch (_) { return null; }
}
const RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
const encoder = new TextEncoder();
const controls = /[\x00-\x1f\x7f]/;
const observations = new WeakMap();
export const dataOf = reply => reply.data && typeof reply.data === 'object' ? reply.data : reply;
export function mergeClipSnapshot(snapshot, current) {
  for (const key of ['network','upload']) {
    if (current[key] && (observations.get(current[key]) || 0) > (observations.get(snapshot[key]) || 0)) snapshot[key] = current[key];
  }
  return snapshot;
}

export function wifiCommand(ssid, password) {
  const nameSize = encoder.encode(ssid).length, passwordSize = encoder.encode(password).length;
  if (nameSize < 1 || nameSize > 32 || passwordSize < 8 || passwordSize > 63 || ssid.includes(',') || controls.test(ssid + password)) {
    throw Error('Wi-Fi 名称需为 1–32 字节且不含逗号，密码为 8–63 字节，不能包含控制字符');
  }
  return `AT+NETCFG=${ssid},${password}`;
}
export function receiverCommand(endpoint, device, token) {
  const match = /^([A-Za-z0-9.-]{1,95}):([0-9]{1,5})$/.exec(endpoint);
  if (!match || +match[2] < 1 || +match[2] > 65535) throw Error('请填写主机:端口，不包含 https:// 或路径');
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(device) || !/^[A-Za-z0-9_-]{32,96}$/.test(token)) throw Error('设备 ID 为 1–32 位，设备令牌为 32–96 位字母、数字、下划线或短横线');
  return `AT+UPLOADCFG=${match[1]},${match[2]},${device},${token}`;
}
export function decodeSsid(value) {
  if (typeof value !== 'string' || !/^(?:[0-9a-fA-F]{2}){0,32}$/.test(value)) throw Error('设备返回的 Wi-Fi 名称编码无效');
  return new TextDecoder('utf-8', {fatal:true}).decode(Uint8Array.from(value.match(/../g) || [], byte => parseInt(byte,16)));
}

export class JsonFramer {
  constructor() { this.decoder = new TextDecoder('utf-8', {fatal:true}); this.text = ''; this.depth = 0; this.quoted = false; this.escaped = false; }
  push(bytes) {
    const rows = [];
    let text;
    try { text = this.decoder.decode(bytes,{stream:true}); } catch (_) { throw Error('设备 JSON 编码无效'); }
    for (const char of text) {
      if (!this.depth) {
        if (/\s/.test(char)) continue;
        if (char !== '{') throw Error('设备响应不是 JSON 对象');
      }
      this.text += char;
      if (this.text.length > 16384) throw Error('设备响应过大');
      if (this.quoted) {
        if (this.escaped) this.escaped = false;
        else if (char === '\\') this.escaped = true;
        else if (char === '"') this.quoted = false;
      } else if (char === '"') this.quoted = true;
      else if (char === '{') { if (++this.depth > 16) throw Error('设备 JSON 嵌套过深'); }
      else if (char === '}') this.depth--;
      if (!this.depth) {
        try { rows.push(JSON.parse(this.text)); } catch (_) { throw Error('设备 JSON 格式无效'); }
        this.text = '';
      }
    }
    return rows;
  }
}

function matches(command, reply) {
  const data = dataOf(reply);
  if (command === 'AT+IDENTITY?') return typeof data.device_uid === 'string' && Number.isInteger(data.binding_protocol_version);
  if (command === 'AT+BINDING?' || command.startsWith('AT+BINDCFG=') || command.startsWith('AT+BINDCLR=')) return typeof data.bound === 'boolean' && typeof data.saved === 'boolean';
  if (command === 'AT+DEVICE') return typeof data.device === 'string';
  if (command === 'AT+VERSION') return typeof reply.firmware === 'string';
  if (command === 'AT+GSTAT') return typeof data.state === 'string' && ('recording' in data || 'battery' in data);
  if (command.startsWith('AT+NETCFG')) return typeof data.configured === 'boolean' && typeof data.ssid_hex === 'string';
  if (command === 'AT+UPLOADCFG?') return typeof data.configured === 'boolean' && typeof data.saved === 'boolean' && !('ssid_hex' in data);
  if (command === 'AT+UPLOADAUTO?') return typeof data.enabled === 'boolean';
  if (command === 'AT+NETCHECK?') return data.scope === 'wifi_dhcp' && typeof data.state === 'string' && Number.isInteger(data.job);
  if (command === 'AT+NETCHECK') return data.accepted === true && Number.isInteger(data.job);
  if (command === 'AT+UPLOAD?') return typeof data.stage === 'string' && typeof data.active === 'boolean';
  return typeof reply.stage === 'string' && typeof reply.active === 'boolean';
}

export class AtClient {
  constructor(write, {timeout = 12000, onClose = () => {}, onEvent = () => {}} = {}) {
    this.write = write; this.timeout = timeout; this.onClose = onClose; this.onEvent = onEvent;
    this.framer = new JsonFramer(); this.pending = null; this.closed = false; this.order = 0;
  }
  close(error = Error('设备已断开，请重新连接后读取状态'), disconnect = true) {
    if (this.closed) return;
    this.closed = true; this.pending?.reject(error); this.onClose(disconnect);
  }
  receive(bytes) {
    if (this.closed) return;
    let rows;
    try { rows = this.framer.push(bytes); } catch (error) { this.close(error); return; }
    for (const reply of rows) {
      observations.set(reply,++this.order); observations.set(dataOf(reply),this.order);
      if (reply.event) { this.onEvent(reply); continue; }
      const pending = this.pending;
      if (!pending || (reply.ok !== true && reply.ok !== false)) continue;
      if (reply.ok === false) {
        const code = Number.isInteger(reply.error) ? `（${reply.error}）` : '';
        const error=Error(`Clip 拒绝操作${code}，请检查固件支持、空闲状态与配置`);
        if(Number.isInteger(reply.error))error.code=reply.error;
        if(reply.error===-16){error.name='ClipBusyError';error.message='等待设备空闲后自动更新配置';}
        if(/AT\+(IDENTITY|BINDING|BINDCFG|BINDCLR)/.test(pending.command)&&reply.msg==='Unknown command'){error.name='UnsupportedBindingError';error.message='旧固件尚不支持自动覆盖绑定，请升级 Boa 固件';}
        pending.reject(error);
      } else if (matches(pending.command, reply)) pending.resolve(reply);
    }
  }
  send(command) {
    if (this.closed) return Promise.reject(Error('请重新连接 Clip 后读取状态'));
    if (this.pending) return Promise.reject(Error('已有设备命令进行中，请稍后操作'));
    const bytes = encoder.encode(command);
    if (bytes.length > 255 || controls.test(command)) return Promise.reject(Error('命令必须在 255 字节内，且不含控制字符；固件不支持命令分片'));
    return new Promise((resolve, reject) => {
      const finish = (callback, value) => { if (this.pending !== job) return; clearTimeout(timer); this.pending = null; callback(value); };
      const job = {command, resolve: value => finish(resolve,value), reject: error => finish(reject,error)};
      const timer = setTimeout(() => this.close(Error('Clip 未确认操作，请重连后读取实际状态')), this.timeout);
      this.pending = job;
      // Each GATT write is a full AT command in this firmware. Never split it.
      Promise.resolve().then(() => this.write(bytes)).catch(() => {
        if (this.pending === job) this.close(Error('蓝牙单条写入失败，请缩短配置或重连；不会自动重试或拆分命令'));
      });
    });
  }
}

export async function connectAt(device, onEvent = () => {}) {
  await disconnectGatt(device);
  const server = await device.gatt.connect();
  let client;
  try {
    const service = await server.getPrimaryService(AT_SERVICE);
    const rx = await service.getCharacteristic(RX), tx = await service.getCharacteristic(TX);
    if (!rx.properties.writeWithoutResponse) throw Error('当前设备缺少 Clip AT 写入能力');
    client = new AtClient(bytes => rx.writeValueWithoutResponse(bytes), {onClose: disconnect => {
      tx.removeEventListener('characteristicvaluechanged', notification);
      device.removeEventListener('gattserverdisconnected', disconnected);
      if (disconnect) disconnectGatt(device).catch(() => {});
    }, onEvent});
    const notification = event => { const value = event.target.value; client.receive(new Uint8Array(value.buffer,value.byteOffset,value.byteLength)); };
    const disconnected = () => { client.close(); tx.removeEventListener('characteristicvaluechanged',notification); device.removeEventListener('gattserverdisconnected',disconnected); };
    tx.addEventListener('characteristicvaluechanged',notification);
    device.addEventListener('gattserverdisconnected',disconnected);
    try { await tx.startNotifications(); } catch (_) { disconnected(); throw Error('Clip 通知订阅失败，请完成系统蓝牙配对后重连'); }
    return client;
  } catch (error) { await disconnectGatt(device).catch(() => {}); throw error; }
}

export class ClipConfigurator {
  constructor(client) { this.client = client; }
  async deviceName() {
    const name=dataOf(await this.client.send('AT+DEVICE')).device;
    if(typeof name!=='string'||!name||encoder.encode(name).length>64||controls.test(name))throw Error('无法读取有效设备名称，请联系开发者检查固件');
    return name;
  }
  async saveReceiverPreserving(endpoint,device,token,guard=()=>{}) {
    const command=receiverCommand(endpoint,device,token);
    if(encoder.encode(command).length>255)throw Error('配置超过蓝牙单条命令长度，请联系开发者');
    const send=async command=>{await guard(command.includes('='));const reply=dataOf(await this.client.send(command));await guard();return reply;};
    const busy=()=>{const error=Error('等待 Clip 空闲后自动配置');error.name='ClipBusyError';throw error;};
    const idle=async()=>{const status=await send('AT+GSTAT');if(String(status.state).toUpperCase()!=='IDLE'||status.recording||status.record_pending)busy();};
    await idle();
    if((await send('AT+UPLOAD?')).active!==false)busy();
    const automatic=await send('AT+UPLOADAUTO?');
    if(typeof automatic.enabled!=='boolean')throw Error('无法确认自动上传开关，未修改配置');
    if(automatic.enabled){
      const existing=await send('AT+UPLOADCFG?');
      if(!existing.saved||!existing.configured)throw Error('自动上传已开启；请先关闭自动上传，再重试配置');
      return {...existing,preserved:true};
    }
    // Do not send UPLOADAUTO=off: older firmware can cancel a concurrently starting upload.
    // UPLOADCFG itself rejects writes if upload becomes enabled/active in the meantime.
    await idle();
    if((await send('AT+UPLOAD?')).active!==false)busy();
    await send(command);
    const saved=await send('AT+UPLOADCFG?');
    if(!saved.saved||!saved.configured)throw Error('设备未确认目标已保存；请重试并核实自动上传开关');
    return saved;
  }
  async idle() {
    const status = dataOf(await this.client.send('AT+GSTAT'));
    if (String(status.state).toUpperCase() !== 'IDLE' || status.recording || status.record_pending) throw Error('请等待 Clip 空闲后再修改配置');
  }
  async read() {
    const value = {unavailable:[]};
    for (const [key, command] of Object.entries({version:'AT+VERSION',status:'AT+GSTAT',wifi:'AT+NETCFG?',receiver:'AT+UPLOADCFG?',automatic:'AT+UPLOADAUTO?',network:'AT+NETCHECK?',upload:'AT+UPLOAD?'})) {
      try { value[key] = dataOf(await this.client.send(command)); }
      catch (error) { if (this.client.closed) throw error; value.unavailable.push(key); }
    }
    return value;
  }
  async saveWifi(ssid,password) {
    const command = wifiCommand(ssid,password);
    await this.idle();
    const saved = dataOf(await this.client.send(command));
    if (!saved.saved || !saved.configured || decodeSsid(saved.ssid_hex) !== ssid) throw Error('设备未确认 Wi-Fi 已保存，请重新读取状态');
    return saved;
  }
  async saveAndCheckWifi(ssid,password,onState,options) {
    const wifi = await this.saveWifi(ssid,password);
    options?.onSaved?.(wifi);
    const network = await this.checkNetwork(onState,options);
    return {wifi,network};
  }
  async saveReceiver(endpoint,device,token) {
    const command = receiverCommand(endpoint,device,token);
    if (encoder.encode(command).length > 255) throw Error('配置超过 255 字节，请缩短主机名或设备令牌');
    await this.idle();
    await this.client.send('AT+UPLOADAUTO=off');
    if (dataOf(await this.client.send('AT+UPLOADAUTO?')).enabled !== false) throw Error('设备未确认关闭自动上传，未修改目标');
    await this.client.send(command);
    const saved = dataOf(await this.client.send('AT+UPLOADCFG?'));
    if (!saved.saved || !saved.configured) throw Error('设备未确认目标已保存，请重新读取状态');
    return saved;
  }
  async automatic(enabled,guard=()=>{}) {
    const check=async live=>{if(await guard(live)===false)throw new DOMException('登录或设备连接已变化','AbortError');};
    if (enabled) {
      const wifi = dataOf(await this.client.send('AT+NETCFG?'));
      const receiver = dataOf(await this.client.send('AT+UPLOADCFG?'));
      if (!wifi.saved || !wifi.configured || !receiver.saved || !receiver.configured) throw Error('请先保存 Wi-Fi 和 Server 配置');
    }
    await check(true);
    await this.client.send(`AT+UPLOADAUTO=${enabled ? 'on' : 'off'}`);
    await check();
    const actual = dataOf(await this.client.send('AT+UPLOADAUTO?'));
    if (actual.enabled !== enabled) throw Error('设备未确认自动上传开关，请刷新后核实');
    return actual;
  }
  async checkNetwork(onState, {interval = 1200, maxPolls = 55} = {}) {
    const accepted = dataOf(await this.client.send('AT+NETCHECK'));
    if (!accepted.accepted || !Number.isInteger(accepted.job)) throw Error('设备未接受网络检查');
    onState({...accepted,state:'checking'});
    const deadline = Date.now() + 65000;
    for (let count = 0; count < maxPolls && Date.now() < deadline; count++) {
      await new Promise(resolve => setTimeout(resolve,interval));
      const row = dataOf(await this.client.send('AT+NETCHECK?'));
      if (row.job !== accepted.job) throw Error('设备网络检查任务已变化，请重新读取状态');
      onState(row);
      if (row.state === 'succeeded' && row.cleanup_error === 0) return row;
      if (['failed','cancelled','succeeded'].includes(row.state)) throw Error(`Wi-Fi 检查未通过（${Number.isInteger(row.error) ? row.error : '未知错误'}），请读取设备状态`);
    }
    throw Error('网络检查结果未确认，请稍后重新读取状态');
  }
}
