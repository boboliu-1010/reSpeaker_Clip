import {decodeSsid} from './clip-config.mjs';

function savedSsid(wifi) {
  try { return wifi?.configured ? decodeSsid(wifi.ssid_hex) : ''; }
  catch (_) { return ''; }
}

// NETCFG is a saved Station configuration; NETCHECK is a historical result.
// Neither alone establishes an ongoing Wi-Fi connection.
export function clipWifiView(clip, {connected=false}={}) {
  const ssid=savedSsid(clip.wifi);
  let connection=!connected ? ssid?'设备已断开 · 显示上次读取':'连接 Clip 后读取' :
    !clip.wifi ? '设备未返回 Wi-Fi 配置' : !clip.wifi.configured ? '尚未配置 Wi-Fi' :
      `${clip.wifi.saved?'已保存':'保存未确认'} · 实时连接状态未知`;
  if(connected && clip.upload?.active) {
    if(['preparing','connecting'].includes(clip.upload.stage)) connection='设备正在连接此 Wi-Fi 配置';
    else if(['tls','sending','verifying'].includes(clip.upload.stage)) connection='设备正在上传 · 使用此 Wi-Fi 配置';
  }
  const network=clip.network;
  let test='尚无网络检测结果';
  if(network?.state==='succeeded' && network.cleanup_error===0) test=`最近检测通过${network.ip?' · IP '+network.ip:''}，不代表当前仍在线`;
  else if(network?.state==='checking') test='最近检测任务正在进行';
  else if(['failed','cancelled'].includes(network?.state)) test='最近网络检测未通过，请重试';
  return {ssid,connection,test};
}

export function wifiNameFromDevice(current, wifi, {edited=false,force=false}={}) {
  return (!edited || force) ? savedSsid(wifi) || current : current;
}

export function toggleWifiPassword(input, button) {
  const visible=input.type==='password';
  input.type=visible?'text':'password';
  button.textContent=visible?'隐藏密码':'显示密码';
  button.setAttribute('aria-pressed',String(visible));
}
