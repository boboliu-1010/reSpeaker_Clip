import {wrapClipOpus,MAX_CLIP_BYTES} from './clip-audio.mjs';
const MAX_STANDARD_BYTES=64*1024*1024;
const idPattern=/^[0-9a-f]{32}$/,hashPattern=/^[0-9a-f]{64}$/;
const abortError=()=>new DOMException('已取消旧录音请求','AbortError');
const checkAbort=signal=>{if(signal?.aborted) throw abortError();};
async function recordingError(response) {
  const body=await response.json().catch(()=>({}));
  if(response.status===409&&body.detail==='session_user_changed'){
    const error=Error('登录用户已在其他页面切换，请重新进入');error.name='SessionChangedError';throw error;
  }
  throw Error(`录音请求失败（HTTP ${response.status}）`);
}
export function sortRecordings(rows) {
  return [...rows].sort((a,b)=>(Number(b.created)||0)-(Number(a.created)||0)||String(b.id).localeCompare(String(a.id)));
}
export function contentPath(row) {
  if(!idPattern.test(row.id)) throw Error('录音 ID 无效');
  if(row.source==='clip_direct') return `/api/boa/v1/audio-files/${row.id}/content`;
  if(row.source==='app_upload') return `/api/audio/recordings/${row.id}/content`;
  throw Error('未知录音来源');
}
export async function loadRecording(row,{token='',cookieSession=false,userId,signal,fetcher=fetch}={}) {
  const path=contentPath(row),limit=row.source==='clip_direct'?MAX_CLIP_BYTES:MAX_STANDARD_BYTES;
  if(typeof token!=='string'||/[\r\n]/.test(token)||(!token.trim()&&!cookieSession)) throw Error('请先登录当前用户');
  if(cookieSession&&!/^[A-Za-z0-9_-]{1,32}$/.test(userId||''))throw Error('请先登录当前用户');
  if(!Number.isSafeInteger(row.size)||row.size<=0||!hashPattern.test(row.sha256)) throw Error('录音长度或 SHA-256 无效');
  if(row.size>limit) throw Error(`该文件超过网页播放上限 ${row.source==='clip_direct'?'8 MiB':'64 MiB'}，请下载后播放`);
  checkAbort(signal);
  const response=await fetcher(path,{headers:token?{Authorization:`Bearer ${token}`}:{'X-Boa-User':userId},credentials:'same-origin',signal,cache:'no-store',redirect:'error'});
  if(!response.ok) await recordingError(response);
  const declared=response.headers.get('Content-Length');
  if(declared!==null && Number(declared)!==row.size) throw Error('录音响应长度与列表不一致');
  const bytes=new Uint8Array(row.size),reader=response.body?.getReader();
  if(!reader) throw Error('浏览器未提供录音下载流');
  let offset=0,complete=false;
  try {
    while(true) {
      checkAbort(signal);
      const {done,value}=await reader.read();if(done) break;
      if(offset+value.length>row.size) throw Error('录音下载长度超过预期');
      bytes.set(value,offset);offset+=value.length;
    }
    if(offset!==row.size) throw Error('录音下载长度不足，请重试');
    complete=true;
  } finally {if(!complete) await reader.cancel().catch(()=>{});reader.releaseLock();}
  checkAbort(signal);
  if(!globalThis.crypto?.subtle) throw Error('请通过 HTTPS 或 localhost 打开网页以校验录音');
  const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
  if([...digest].map(x=>x.toString(16).padStart(2,'0')).join('')!==row.sha256) throw Error('录音 SHA-256 校验失败，未播放');
  checkAbort(signal);
  if(row.source==='clip_direct') return {...wrapClipOpus(bytes),mime:'audio/ogg'};
  return {bytes,mime:row.mime,duration:null};
}
export class PlaybackRequests {
  constructor(loader=loadRecording) {this.loader=loader;this.revision=0;this.controller=null;}
  reset() {this.revision++;this.controller?.abort();this.controller=null;}
  async load(row,session) {
    this.reset();const revision=this.revision,controller=new AbortController();this.controller=controller;
    let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},60000);
    try {
      const result=await this.loader(row,{token:session.token,cookieSession:session.cookieSession,userId:session.userId,signal:controller.signal});
      if(revision!==this.revision||controller.signal.aborted) throw abortError();
      return result;
    } catch(error) {if(revision!==this.revision)throw abortError();if(timedOut) throw Error('录音加载超时，请重试');throw error;}
    finally {clearTimeout(timer);if(this.controller===controller) this.controller=null;}
  }
}

export function mountRecordings({session,notify,onSessionMismatch=()=>{}}) {
  const $=id=>document.getElementById(id),audio=$('recording-audio'),requests=new PlaybackRequests();
  let rows=[],more=false,listController=null,listRevision=0,url=null,selected=null;
  const element=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
  const time=value=>{value=Number.isFinite(value)?Math.max(0,value):0;return `${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;};
  const size=value=>value<1024*1024?`${(value/1024).toFixed(1)} KiB`:`${(value/1024/1024).toFixed(1)} MiB`;
  function stop() {
    requests.reset();audio.pause();audio.removeAttribute('src');audio.load();
    if(url) URL.revokeObjectURL(url);url=null;selected=null;
    $('recording-player-title').textContent='选择一条录音，开始播放';
    $('recording-player-note').textContent='Clip 原始音频在当前浏览器中解码。';
    $('recording-toggle').disabled=true;$('recording-seek').disabled=true;
    $('recording-toggle').textContent='播放';$('recording-seek').value=0;$('recording-time').textContent='0:00 / 0:00';
  }
  function render() {
    const container=$('recording-list');container.replaceChildren();
    if(!rows.length) container.append(element('div',session()?'还没有录音。Clip 上传完成后，点击刷新。':'登录后查看属于你的录音。','recording-empty'));
    for(const row of rows) {
      const item=element('div',undefined,'recording-row'),details=element('div',undefined,'recording-details');
      details.append(element('strong',row.filename),element('small',`${row.source==='clip_direct'?'Clip 录音':'App 上传'} · ${size(row.size)} · 上传 ${new Date(row.created*1000).toLocaleString()}`));
      const play=element('button',selected===row.id?'从头播放':'播放','secondary');play.type='button';
      play.setAttribute('aria-label',`播放 ${row.filename}`);play.addEventListener('click',()=>playRecording(row));
      item.append(element('span','♪','recording-icon'),details,play);container.append(item);
    }
    $('recording-count').textContent=String(rows.length);$('recording-more').hidden=!more;
    $('recording-refresh').disabled=!session();
  }
  function updateTime() {
    const duration=Number.isFinite(audio.duration)?audio.duration:0;
    $('recording-time').textContent=`${time(audio.currentTime)} / ${time(duration)}`;
    $('recording-seek').value=duration?Math.round(audio.currentTime/duration*1000):0;
  }
  audio.addEventListener('loadedmetadata',()=>{
    $('recording-seek').disabled=!(Number.isFinite(audio.duration)&&audio.duration>0);
    $('recording-player-note').textContent=`可播放 · ${audio.duration.toFixed(2)} 秒 · 原件校验通过`;
    updateTime();
  });
  audio.addEventListener('timeupdate',updateTime);
  audio.addEventListener('play',()=>{$('recording-toggle').textContent='暂停';});
  audio.addEventListener('pause',()=>{$('recording-toggle').textContent=audio.ended?'重新播放':'继续播放';});
  audio.addEventListener('ended',()=>{$('recording-toggle').textContent='重新播放';$('recording-player-note').textContent=`播放结束 · ${audio.duration.toFixed(2)} 秒`;updateTime();});
  audio.addEventListener('error',()=>{if(url) {$('recording-player-note').textContent='Chrome 无法解码此录音，请下载原文件检查';$('recording-toggle').disabled=true;}});
  $('recording-seek').addEventListener('input',()=>{if(Number.isFinite(audio.duration))audio.currentTime=audio.duration*Number($('recording-seek').value)/1000;});
  $('recording-toggle').addEventListener('click',async()=>{
    try {if(audio.paused){if(audio.ended)audio.currentTime=0;await audio.play();}else audio.pause();}
    catch(_){$('recording-player-note').textContent='请点击播放，或检查浏览器声音设置';}
  });
  async function playRecording(row) {
    const current=session();if(!current)return;
    if(row.source==='clip_direct'&&!audio.canPlayType('audio/ogg; codecs="opus"')) {notify('当前浏览器不支持 Ogg Opus，请使用 Chrome',true);return;}
    stop();selected=row.id;render();$('recording-player-title').textContent=row.filename;
    $('recording-player-note').textContent='正在下载、校验并准备播放…';
    try {
      const result=await requests.load(row,current);
      if(session()?.token!==current.token||session()?.userId!==current.userId) return;
      url=URL.createObjectURL(new Blob([result.bytes],{type:result.mime}));audio.src=url;audio.load();
      $('recording-toggle').disabled=false;
      try {await audio.play();}catch(error){if(error.name==='NotAllowedError')$('recording-player-note').textContent='已加载，请点击“播放”';else throw error;}
    } catch(error) {if(error.name!=='AbortError'){if(error.name==='SessionChangedError'){reset();onSessionMismatch();}$('recording-player-note').textContent=error.message;notify(error.message,true);}}
  }
  async function refresh(append=false) {
    const current=session();if(!current){reset();return;}
    listController?.abort();listController=new AbortController();const revision=++listRevision;
    const controller=listController,offset=append?rows.length:0;
    let timedOut=false;const timer=setTimeout(()=>{timedOut=true;controller.abort();},30000);
    $('recording-refresh').disabled=true;$('recording-more').disabled=true;
    $('recording-feedback').textContent='正在读取你的录音…';
    try {
      const response=await fetch(`/api/boa/v1/audio-files?offset=${offset}&limit=50`,{headers:current.token?{Authorization:`Bearer ${current.token}`}:{'X-Boa-User':current.userId},credentials:'same-origin',signal:controller.signal,cache:'no-store',redirect:'error'});
      if(!response.ok)await recordingError(response);
      const result=await response.json();
      if(revision!==listRevision||session()?.token!==current.token||session()?.userId!==current.userId)return;
      if(!Array.isArray(result.items))throw Error('录音列表格式无效');
      rows=sortRecordings([...new Map([...(append?rows:[]),...result.items].map(row=>[row.id,row])).values()]);more=result.items.length===50;
      render();$('recording-feedback').textContent=`当前用户 ${current.userId} · 已加载 ${rows.length} 条 · 上传时间从新到旧`;
    } catch(error) {
      if(revision!==listRevision||session()?.token!==current.token||session()?.userId!==current.userId)return;
      if(error.name==='SessionChangedError'){reset();onSessionMismatch();notify(error.message,true);}
      if(revision===listRevision&&(error.name!=='AbortError'||timedOut))$('recording-feedback').textContent=timedOut?'录音列表加载超时，请刷新重试':error.message;
    } finally {clearTimeout(timer);if(revision===listRevision){$('recording-refresh').disabled=!session();$('recording-more').disabled=false;}}
  }
  function reset() {
    listRevision++;listController?.abort();listController=null;stop();rows=[];more=false;
    $('recording-feedback').textContent='文件按登录用户隔离；点击播放后才下载。';render();
  }
  $('recording-refresh').addEventListener('click',()=>refresh());$('recording-more').addEventListener('click',()=>refresh(true));
  reset();return {refresh,reset};
}
