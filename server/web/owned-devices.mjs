// Per-login list of Server-owned devices. No credentials are rendered here.
export function mountOwnedDevices({session,service,notify,onUnbind}) {
  const list=document.getElementById('owned-devices'),status=document.getElementById('owned-devices-status');
  let request=0;
  const element=(tag,text)=>{const item=document.createElement(tag);item.textContent=text;return item;};
  return {
    reset(){request++;list.replaceChildren();status.textContent='登录后查看已分配设备。';},
    async refresh(){
      const identity=session(),operation=++request;
      const current=()=>operation===request&&identity?.key===session()?.key;
      if(!identity){list.replaceChildren();status.textContent='登录后查看已分配设备。';return;}
      status.textContent='正在读取你的设备…';
      try {
        const rows=await service.devices();if(!current())return;
        list.replaceChildren();
        status.textContent=rows.length?`${rows.length} 台设备 · 上传时间只表示该绑定的 Server 收件记录`:'尚无可用设备；请联系开发者登记完整 UID。';
        for(const row of rows){
          if(!/^[A-Za-z0-9_-]{1,32}$/.test(row.device_id||''))throw Error('设备列表身份无效');
          const item=element('div','');item.className='binding-device';
          const info=element('div','');info.append(element('strong',row.device_name||row.device_id));
          info.append(element('small',row.device_uid?`UID ${row.device_uid}`:'完整 UID 待登记'));
          info.append(element('small',row.provisioning_state==='revoked'?'已解绑':row.provisioning_state==='provisioned'?'客户端已确认写入':'已登记，待配置'));
          if(row.last_received_at)info.append(element('small',`此绑定最近收件 ${new Date(row.last_received_at*1000).toLocaleString()}`));
          if(row.device_cleanup_pending)info.append(element('small','设备本地清理待完成；交接由开发者处理'));
          const retryCleanup=row.provisioning_state==='revoked'&&row.device_cleanup_pending;
          const control=element('button',retryCleanup?'清理设备':'解绑');control.className='secondary';control.disabled=row.provisioning_state==='revoked'&&!retryCleanup;
          control.addEventListener('click',async()=>{if(!current())return;try{await onUnbind(row);if(current())await this.refresh();}catch(error){if(current()&&error.name!=='AbortError')notify(error.message,true);}});
          item.append(info,control);list.append(item);
        }
      } catch(error){if(!current())return;list.replaceChildren();status.textContent='设备列表暂不可用，请刷新重试。';if(error.name!=='AbortError')notify(error.message,true);}
    },
  };
}
