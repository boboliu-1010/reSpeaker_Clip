import {dataOf,receiverCommand} from './clip-config.mjs';

export const validUid=value=>typeof value==='string'&&/^(?:[0-9a-f]{2}){8,32}$/.test(value);
const validId=value=>typeof value==='string'&&/^[0-9a-f]{32}$/.test(value);
const uint32=value=>Number.isInteger(value)&&value>0&&value<=0xffffffff;
const abort=()=>new DOMException('登录或设备连接已变化','AbortError');
function busy(){const error=Error('等待设备空闲后自动更新配置');error.name='ClipBusyError';return error;}

export function bindingCommand(profile) {
  if(!validUid(profile.device_uid)||!validId(profile.binding_id)||!uint32(profile.epoch)||!uint32(profile.revision))throw Error('Server 绑定身份或版本无效');
  const receiver=receiverCommand(profile.endpoint,profile.device_id,profile.device_token);
  const command=receiver.replace('AT+UPLOADCFG=','AT+BINDCFG=')+`,${profile.binding_id},${profile.epoch},${profile.revision}`;
  if(new TextEncoder().encode(command).length>255)throw Error('绑定配置超过 255 字节，请联系开发者调整');
  return command;
}
function snapshot(value) {
  if(!validUid(value.device_uid)||typeof value.bound!=='boolean'||typeof value.saved!=='boolean')throw Error('设备绑定状态无效');
  if(value.bound&&(!validId(value.binding_id)||!uint32(value.epoch)||!uint32(value.revision)))throw Error('设备绑定版本无效');
  return value;
}
export function bindingMatches(value,profile) {
  return value.bound===true&&value.saved===true&&value.device_uid===profile.device_uid&&value.binding_id===profile.binding_id&&value.epoch===profile.epoch&&value.revision===profile.revision;
}

export class ClipBindingConfigurator {
  constructor(client){this.client=client;}
  async send(command,guard=()=>{}) {
    if(await guard(command.includes('='))===false)throw abort();
    const result=dataOf(await this.client.send(command));
    if(await guard(false)===false)throw abort();
    return result;
  }
  async identity(guard) {
    const value=await this.send('AT+IDENTITY?',guard);
    if(!validUid(value.device_uid)||value.binding_protocol_version!==1)throw Error('设备绑定协议版本不支持，请先升级固件');
    return value;
  }
  async readBinding(guard){return snapshot(await this.send('AT+BINDING?',guard));}
  async idle(guard) {
    const status=await this.send('AT+GSTAT',guard);
    if(String(status.state).toUpperCase()!=='IDLE'||status.recording||status.record_pending)throw busy();
    if((await this.send('AT+UPLOAD?',guard)).active!==false)throw busy();
  }
  async saveBinding(profile,guard) {
    const command=bindingCommand(profile);
    const before=await this.readBinding(guard);
    if(before.device_uid!==profile.device_uid)throw Error('所连设备 UID 与 Server 登记不一致');
    if(before.bound&&(before.binding_id!==profile.binding_id||before.epoch!==profile.epoch))throw Error('设备仍有其他绑定，请联系开发者完成换绑清理');
    if(before.bound&&before.revision>profile.revision)throw Error('设备配置版本较新，请联系开发者核对 Server 版本');
    await this.idle(guard);
    const automatic=await this.send('AT+UPLOADAUTO?',guard);
    if(typeof automatic.enabled!=='boolean')throw Error('无法确认上传开关，未修改绑定');
    // Firmware makes admission and persistence atomic; no Wi-Fi/storage/off/on commands.
    const accepted=snapshot(await this.send(command,guard));
    if(!bindingMatches(accepted,profile))throw Error('设备未确认绑定配置已保存');
    const actual=await this.readBinding(guard);
    if(!bindingMatches(actual,profile))throw Error('设备读回未确认当前绑定版本');
    if((await this.send('AT+UPLOADAUTO?',guard)).enabled!==automatic.enabled)throw Error('配置已保存，但上传开关发生变化，请核实');
    return actual;
  }
  async clearBinding(profile,guard) {
    if(!validUid(profile.device_uid)||!validId(profile.binding_id)||!uint32(profile.revision))throw Error('解绑目标无效');
    const current=await this.readBinding(guard);
    if(current.device_uid!==profile.device_uid)throw Error('所连设备不是解绑目标');
    if(!current.bound){
      const receiver=await this.send('AT+UPLOADCFG?',guard),automatic=await this.send('AT+UPLOADAUTO?',guard);
      if(receiver.saved!==true||receiver.configured!==false||automatic.enabled!==false)throw Error('设备上传凭证尚未确认清除，本地清理待完成');
      return current;
    }
    if(current.binding_id!==profile.binding_id||current.revision!==profile.revision)throw Error('设备绑定已变化，不清理新的配置');
    await this.idle(guard);
    const cleared=await this.send(`AT+BINDCLR=${profile.binding_id},${profile.revision}`,guard);
    if(cleared.saved!==true||cleared.bound!==false||cleared.cleared_binding_id!==profile.binding_id)throw Error('设备未确认清理完成');
    const actual=await this.readBinding(guard);
    if(actual.device_uid!==profile.device_uid||actual.bound||!actual.saved)throw Error('设备清理读回未通过');
    return actual;
  }
}
