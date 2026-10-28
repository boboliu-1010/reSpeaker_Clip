import {bindingCommand,bindingMatches,validUid} from './clip-binding.mjs';

const changed=()=>{const error=Error('Server 配置已更新，正在重新获取');error.name='ConfigurationChangedError';return error;};
const fingerprint=async p=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([
  p.device_uid,p.device_id,p.owner_id,p.binding_id,p.epoch,p.revision,p.endpoint,p.device_token,
]))))).map(b=>b.toString(16).padStart(2,'0')).join('');

export class AutomaticClipBinding {
  constructor(){this.completed=new WeakMap();}
  async configure({config,owner,getProfile,confirm,isCurrent,onIdentity}) {
    const guard=async live=>{if(!await isCurrent(live))throw new DOMException('登录或设备连接已变化','AbortError');};
    await guard(false);
    let identity;
    try {identity=await config.identity(guard);}
    catch(error){if(error.name==='UnsupportedBindingError')error.legacyAllowed=true;throw error;}
    await guard(false);onIdentity?.(identity);
    let profile=await getProfile(identity);await guard(false);
    const validate=p=>{
      if(p?.owner_id!==owner||p?.device_uid!==identity.device_uid)throw Error('Server 配置与当前用户或设备不一致');
      bindingCommand(p);
    };
    try {
      validate(profile);const hash=await fingerprint(profile);await guard(false);
      const previous=this.completed.get(config.client);
      if(previous?.hash===hash&&previous.result.owner_id===owner){
        const current=await config.readBinding(guard);
        if(bindingMatches(current,profile))return previous.result;
      }
      const writeGuard=async live=>{
        await guard(live);
        if(live){
          let latest=await getProfile(identity);await guard(false);validate(latest);
          const actual=await fingerprint(latest);latest=null;await guard(false);
          if(actual!==hash)throw changed();
        }
      };
      await config.saveBinding(profile,writeGuard);await guard(false);
      const receipt=await confirm(profile);await guard(false);
      if(receipt?.state!=='provisioned'||receipt.binding_id!==profile.binding_id||receipt.revision!==profile.revision)throw Error('Server 未确认客户端配置记录');
      const result={device_uid:profile.device_uid,device_id:profile.device_id,device_name:profile.device_name,owner_id:owner,
        binding_id:profile.binding_id,epoch:profile.epoch,revision:profile.revision,endpoint:profile.endpoint,state:'provisioned'};
      this.completed.set(config.client,{hash,result});return result;
    } finally {profile=null;}
  }
}

export class BindingService {
  constructor(request){this.request=request;}
  async devices(){
    const value=await this.request('/devices');
    if(!Array.isArray(value?.items)||value.items.length>1000)throw Error('设备列表无效');
    return value.items;
  }
  async profile(identity) {
    if(!validUid(identity.device_uid))throw Error('设备 UID 无效');
    const devices=(await this.devices()).filter(row=>row.device_uid===identity.device_uid);
    if(!devices.length)throw Error('此设备尚未登记到当前用户，请联系开发者登记完整 UID');
    if(devices.length!==1)throw Error('设备 UID 登记重复，请联系开发者');
    const id=devices[0].device_id;
    if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,32}$/.test(id))throw Error('设备 ID 无效');
    return this.request(`/devices/${id}/binding`,{method:'POST',body:{device_uid:identity.device_uid}});
  }
  confirm(profile){return this.request(`/devices/${profile.device_id}/binding/confirm`,{method:'POST',body:{device_uid:profile.device_uid,binding_id:profile.binding_id,revision:profile.revision,saved:true}});}
  revoke(id){
    if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,32}$/.test(id))throw Error('设备 ID 无效');
    return this.request(`/devices/${id}/binding`,{method:'DELETE'});
  }
}
