import {receiverCommand} from './clip-config.mjs';

// Cache only non-secret confirmation, scoped to this GATT client and login.
export class AutomaticClipConfiguration {
  constructor() { this.completed=new WeakMap(); }
  async configure({config,owner,getProfile,isCurrent}) {
    const guard=async(revalidate=false)=>{if(!await isCurrent(revalidate))throw new DOMException('登录或设备连接已变化','AbortError');};
    await guard();
    const previous=this.completed.get(config.client);
    const name=previous?.result.owner===owner?previous.result.device_name:await config.deviceName();await guard();
    let profile=await getProfile(name);await guard();
    if(profile?.owner!==owner||profile?.device_name!==name)throw Error('设备配置与当前用户或所连设备不一致');
    receiverCommand(profile.endpoint,profile.device_id,profile.device_token);
    try {
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(profile))))).map(b=>b.toString(16).padStart(2,'0')).join('');
      await guard();
      if(previous?.hash===hash&&previous.result.owner===owner)return previous.result;
      const saved=await config.saveReceiverPreserving(profile.endpoint,profile.device_id,profile.device_token,guard);
      await guard();
      const result={device_id:profile.device_id,device_name:name,owner,endpoint:profile.endpoint,preserved:saved.preserved===true};
      if(!result.preserved)this.completed.set(config.client,{result,hash});
      return result;
    } finally { profile=null; }
  }
}
