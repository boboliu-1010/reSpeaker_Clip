import {SMP_SERVICES, connectSmp, disconnectGatt, FirmwareUpdater, hex} from './smp.mjs';
import {AT_SERVICE, connectAt, ClipConfigurator, decodeSsid, mergeClipSnapshot, grantedClip} from './clip-config.mjs';
import {mountRecordings} from './recordings.mjs';
import {ServerConnection} from './server-connection.mjs';
import {WebSession} from './web-session.mjs';
import {AutomaticClipConfiguration} from './device-configuration.mjs';
import {AutomaticClipBinding,BindingService} from './binding-configuration.mjs';
import {ClipBindingConfigurator} from './clip-binding.mjs';
import {mountOwnedDevices} from './owned-devices.mjs';
import {clipWifiView,wifiNameFromDevice,toggleWifiPassword} from './wifi-form.mjs';
const $ = id => document.getElementById(id);
const API = '/api/boa/experimental/firmware';
const state = {token: '', cookieSession: false, cookieUser: '', authBusy: false, caps: null, releases: [], history: [], selected: null, device: null, client: null, at: null, clip: {}, busy: false, attempt: null, detachAttempt: false};
const recordings = mountRecordings({session: () => state.caps ? {token:state.token,cookieSession:state.cookieSession,userId:state.caps.user_id} : null, notify, onSessionMismatch: clearIdentity});
const serverConnection = new ServerConnection({onChange: () => renderControls()});
const webSession = new WebSession();
let authRevision=0;
let receiverSetup=new AutomaticClipConfiguration();
let bindingSetup=new AutomaticClipBinding();
let receiverTimer;
let wifiEdited=false, wifiNameEdited=false;
let messageTimer;
const bindingService=new BindingService(bindingRequest);
const ownedDevices=mountOwnedDevices({session:()=>state.caps?{key:`${authRevision}:${state.caps.user_id}`} :null,service:bindingService,notify,onUnbind:unbindDevice});
function notify(text, error = false) {
  $('message').textContent = text; $('message').hidden = false; $('message').classList.toggle('error', error);
  clearTimeout(messageTimer); messageTimer = setTimeout(() => $('message').hidden = true, error ? 18000 : 7000);
}
function action(id, handler) {
  $(id).addEventListener('click', async () => { try { await handler(); } catch (error) { if(error.name!=='AbortError')notify(error.message, true); } finally { renderControls(); } });
}
function requireAuthRevision(revision) {if(revision!==authRevision)throw new DOMException('旧身份请求已取消','AbortError');}
async function api(path, options = {}, base = API) {
  if (!state.token&&!state.cookieSession) throw Error('请先登录');
  const revision=authRevision;
  const response = await fetch(base + path, {...options, credentials:'same-origin', headers: {...(state.token?{Authorization: `Bearer ${state.token}`} : {'X-Boa-User':state.cookieUser}), ...options.headers}, cache: 'no-store', redirect: 'error'});
  requireAuthRevision(revision);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    requireAuthRevision(revision);
    if(response.status===409&&body.detail==='session_user_changed'){clearIdentity();throw Error('登录用户已在其他页面切换，请重新进入');}
    const error=Error(`${typeof body.detail === 'string' ? body.detail : '请求失败'}（HTTP ${response.status}）`);
    error.status=response.status;error.detail=body.detail;
    if(body.detail==='binding_configuration_changed'){error.name='ConfigurationChangedError';error.message='Server 配置已更新，正在重新获取';}
    throw error;
  }
  return response;
}
async function json(path, body, method = 'POST') {
  const revision=authRevision;
  const options = body === undefined ? {method} : {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const result=await (await api(path,options)).json();requireAuthRevision(revision);return result;
}
function node(tag, text, className) { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; }
function button(text, click, disabled = false) {
  const item = node('button', text, 'secondary'); item.disabled = disabled;
  item.addEventListener('click', async () => { try { await click(); } catch (error) { notify(error.message, true); } }); return item;
}
const stateNames = {draft: '草稿', published: '已发布', withdrawn: '已撤下', uploading: '上传中', awaiting_reconnect: '待重连核实', succeeded: '已核实成功', failed: '未完成'};
function renderControls() {
  // Keep an in-flight updater's references until its own cleanup completes.
  if(state.detachAttempt&&!state.busy){state.attempt=null;state.detachAttempt=false;}
  const developer = state.caps?.role === 'developer';
  const online = serverConnection.status === 'online';
  const connecting = serverConnection.status === 'connecting';
  $('identity').textContent = state.caps ? `${state.caps.user_id} · ${developer ? '开发者' : '用户'}` : online ? '已连接 Boa Server · 请登录' : connecting ? '正在连接 Boa Server…' : 'Boa Server 连接失败';
  $('server-status').textContent = online ? '服务在线' : connecting ? '自动连接当前 Server…' : '连接失败，请检查网络或证书后重试';
  $('server-retry').hidden = online || connecting;
  $('role').textContent = state.caps ? developer ? '开发者视图' : '用户视图' : '未连接';
  $('server-dot').style.background = online ? '#458866' : connecting ? '#95a49b' : '#b54b3e';
  $('developer-panel').hidden = !developer;
  for (const id of ['token', 'user-id', 'login']) $(id).hidden = !!state.caps;
  $('manual-login').hidden = !!state.caps;
  $('login').disabled = state.authBusy || state.busy;
  $('developer-login').disabled = state.authBusy || state.busy;
  $('logout').hidden = !state.caps;
  $('logout').disabled = state.busy || !!state.attempt || state.authBusy;
  $('refresh').disabled = !state.caps || state.busy;
  $('import').disabled = !developer || !$('firmware-file').files.length || state.busy;
  $('trust-status').textContent = state.caps?.trusted_key_configured ? '已配置可信公钥。导入后仍需验签与发布；演示包禁止刷写。' : 'Server 未配置可信公钥：可导入检查，不能发布或升级。';
  const selected = state.selected;
  $('selected-name').textContent = selected ? `${selected.version} · ${selected.profile_id || '待核实镜像'}` : '从左侧选择固件';
  let reason = '请选择已发布的标准 BLE 固件';
  const allowed = !state.caps?.demo_mode && selected?.state === 'published' && ['ble-standard', 'boa-dtls-ota-v1'].includes(selected?.profile_id) && selected?.verification === 'trusted';
  if (selected?.profile_id === 'dtls-upload') reason = '此配置拒绝应用 DFU，需先修改固件';
  else if (selected?.profile_id === 'demo-offline') reason = '演示制品不能刷写到 Clip';
  else if (allowed) reason = '只更新应用核；升级后需重连核实';
  if (allowed && selected.profile_id === 'boa-dtls-ota-v1') reason = '只更新应用核；覆盖式升级，无自动回滚。设备须已安装支持原生 SMP OTA 的固件。';
  if (state.caps?.demo_mode) reason = '本地演示模式禁止实际刷写，可验证固件管理流程';
  $('upgrade-reason').textContent = reason;
  $('upgrade').disabled = !allowed || !state.device?.gatt.connected || !$('compatible').checked || state.busy || !!state.attempt;
  $('connect-device').disabled = !navigator.bluetooth || !state.caps || state.busy;
  $('disconnect').disabled = !state.device?.gatt.connected;
  $('verify').disabled = !state.attempt || state.busy;
  $('end-attempt').disabled = !state.attempt || state.busy;
  $('config-connect').disabled = $('connect-device').disabled;
  $('config-disconnect').disabled = $('disconnect').disabled;
  const configurationReady = state.at && !state.at.closed && state.device?.gatt.connected;
  for (const id of ['config-refresh','save-wifi','configure-receiver','check-wifi','auto-on','auto-off']) $(id).disabled = !configurationReady || state.busy || !!state.attempt;
  for (const id of ['clip-ssid','clip-password']) $(id).disabled = state.busy || !!state.attempt;
  $('config-connected').textContent = configurationReady ? 'AT 通道已连接' : '未连接配置通道';
  if (state.busy) {
    document.querySelectorAll('#release-list button, #history-list button').forEach(item => { item.disabled = true; });
  }
}
function renderReleases() {
  const tbody = $('release-list'); tbody.replaceChildren();
  $('empty').hidden = state.releases.length > 0;
  if (state.caps) {
    $('empty').querySelector('strong').textContent = '还没有可见的固件版本';
    $('empty').querySelector('p').textContent = state.caps.role === 'developer' ? '从下方导入 signed.bin，验签后发布。' : '开发者发布后，版本会出现在这里。';
  }
  for (const release of state.releases) {
    const tr = node('tr'); tr.classList.toggle('selected-row', state.selected?.id === release.id);
    const name = node('td'); name.append(node('strong', release.version), node('small', release.filename), node('small', `${(release.size / 1024).toFixed(1)} KiB · ${release.sha256.slice(0, 10)}…`));
    const profile = node('td'); profile.append(node('span', release.profile_id), node('small', release.verification === 'trusted' ? '可信公钥验签通过' : '未通过可信公钥验签'));
    const status = node('td'); status.append(node('span', stateNames[release.state], `tag ${release.state === 'published' ? 'green' : 'amber'}`));
    const actions = node('td');
    actions.append(button('选择', () => { state.selected = release; renderReleases(); renderControls(); }, state.busy || !!state.attempt));
    actions.append(button('下载', async () => {
      const bytes = new Uint8Array(await (await api(`/releases/${release.id}/content`)).arrayBuffer());
      if (hex(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))) !== release.sha256) throw Error('固件下载哈希不一致');
      const url = URL.createObjectURL(new Blob([bytes])); const link = node('a'); link.href = url; link.download = release.filename;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000); notify('下载完成，SHA-256 校验一致');
    }, release.state === 'withdrawn'));
    if (state.caps.role === 'developer' && release.state !== 'withdrawn') {
      const publish = release.state === 'draft';
      actions.append(button(publish ? '发布' : '撤下', async () => { await json(`/releases/${release.id}/${publish ? 'publish' : 'withdraw'}`, undefined); await refresh(); notify(publish ? '固件已发布' : '固件已撤下'); }, state.busy || (publish && release.verification !== 'trusted')));
    }
    tr.append(name, profile, status, actions); tbody.append(tr);
  }
  $('nav-count').textContent = state.releases.length;
  $('count-all').textContent = state.releases.length;
  $('count-published').textContent = state.releases.filter(r => r.state === 'published').length;
}
function renderHistory() {
  const container = $('history-list'); container.replaceChildren();
  if (!state.history.length) container.textContent = '尚无升级记录。每次操作的进度与结果会显示在这里。';
  for (const attempt of state.history) {
    const row = node('div', undefined, 'history-item');
    row.append(node('span', attempt.device_label), node('span', new Date(attempt.created * 1000).toLocaleString()), node('span', stateNames[attempt.state], 'tag'));
    if (attempt.state === 'awaiting_reconnect') row.append(button('继续核实', () => { state.attempt = attempt; state.selected = {image_hash: attempt.expected_image_hash, version: attempt.expected_image_hash.slice(0, 10)}; renderControls(); notify('选择对应 Clip，然后点击重连核实。'); }, state.busy));
    if (['uploading', 'awaiting_reconnect'].includes(attempt.state)) row.append(button('结束记录', () => endAttempt(attempt), state.busy));
    container.append(row);
  }
  $('count-history').textContent = state.history.length;
}
async function refresh() {
  const revision=authRevision;
  const [releases, history] = await Promise.all([json('/releases', undefined, 'GET'), json('/upgrades', undefined, 'GET')]);
  requireAuthRevision(revision);
  state.releases = releases.items; state.history = history.items;
  if (state.selected?.id) state.selected = state.releases.find(r => r.id === state.selected.id) || null;
  renderReleases(); renderHistory(); renderControls();
  // Audio failures or slow lists must not hold firmware/OTA operations busy.
  void recordings.refresh();
  void ownedDevices.refresh();
}
function renderClip() {
  const c = state.clip, runtime = c.status || {}, auto = c.automatic || {}, upload = c.upload || {};
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  $('clip-runtime').textContent = c.status ? `${runtime.state || '未知'} · 电量 ${finite(runtime.battery) ? runtime.battery + '%' : '未知'} · 剩余 ${finite(runtime.free_space) ? runtime.free_space + ' MB' : '未知'} · ${c.version?.firmware || '版本未知'}` : '连接后读取版本、电量与容量';
  const wifi=clipWifiView(c,{connected:!!state.device?.gatt.connected && !!state.at && !state.at.closed});
  $('clip-wifi').textContent = wifi.ssid || '未读取到设备 Wi-Fi';
  $('clip-wifi-connection').textContent = wifi.connection;
  $('clip-wifi-last-check').textContent = wifi.test;
  const automatic = auto.enabled === true ? '自动上传已开启' : auto.enabled === false ? '自动上传已关闭' : '自动上传未知';
  $('clip-upload-config').textContent = `${c.receiver ? c.receiver.configured && c.receiver.saved ? '目标已配置' : '目标未确认配置' : '目标配置未知'} · ${automatic}`;
  $('clip-automatic').textContent = `${automatic}${auto.paused ? ' · 当前调度暂停' : ''}`;
  $('clip-clock').textContent = auto.time_ready === true ? '设备时间已同步' : auto.time_ready === false ? '设备时间待同步' : '设备时间未知';
  $('clip-stage').textContent = upload.stage ? `设备上传阶段：${upload.stage}` : '上传状态尚未读取';
  const size = finite(upload.size) ? upload.size : 0, confirmed = finite(upload.confirmed) ? upload.confirmed : 0;
  $('clip-transfer-progress').value = size > 0 ? Math.min(1,Math.max(0,confirmed/size)) : 0;
  $('clip-confirmed').textContent = c.upload ? `设备持久确认 ${confirmed} / ${size} 字节 · 错误 ${finite(upload.last_error) ? upload.last_error : 0}${upload.delete_after_upload ? ' · 固件确认整段上传后会清理设备副本' : ''}` : '持久确认字节数未知';
  const network = wifiEdited ? null : c.network;
  $('clip-network-status').textContent = !network ? '网络尚未检查。检查仅验证 Wi-Fi 与 DHCP。' : network.cleanup_error ? '网络检查清理失败，请重新读取状态' : network.state === 'succeeded' ? `Wi-Fi 与 DHCP 已通过（${network.ip || 'IP 未返回'}），尚未验证 Server` : network.state === 'checking' ? '正在检查 Wi-Fi 与 DHCP…' : `Wi-Fi 检查状态：${network.state || '未知'}，错误 ${finite(network.error) ? network.error : 0}`;
}
async function readClip(config = new ClipConfigurator(state.at)) {
  state.clip = mergeClipSnapshot(await config.read(),state.clip);
  $('clip-ssid').value = wifiNameFromDevice($('clip-ssid').value,state.clip.wifi,{edited:wifiNameEdited});
  renderClip();
  if (state.clip.unavailable.length) $('clip-config-feedback').textContent = '部分配置命令未被固件接受；可见信息来自已读取的项目，请核对当前固件能力。';
}
async function bindingRequest(path,options={}) {
  const revision=authRevision;
  const value=await (await api(path,{method:options.method||'GET',signal:AbortSignal.timeout(10000),
    ...(options.body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(options.body)})},'/api/boa/v1')).json();
  requireAuthRevision(revision);return value;
}
async function unbindDevice(row) {
  if(state.busy||state.authBusy||state.attempt)throw Error('请等待当前操作完成后解绑');
  const cleanup=row.provisioning_state==='revoked';
  if(cleanup&&(!state.at||state.at.closed||!state.device?.gatt.connected))throw Error('请先连接对应 Clip，再清理本地上传凭证');
  if(!window.confirm(cleanup?'清理所连 Clip 的旧上传凭证？Wi-Fi 和录音保留。':'解绑会停止该设备上传；云端录音、Wi-Fi 和设备录音保留。确定继续？'))return;
  const revision=authRevision;
  state.busy=true;renderControls();
  try {
    await bindingService.revoke(row.device_id);requireAuthRevision(revision);resetReceiverSetup();
    $('receiver-status').textContent='Server 已解绑并撤销凭证；设备本地清理待完成。';
    if(state.at&&!state.at.closed&&state.device?.gatt.connected&&row.device_uid&&row.binding_id){
      const config=new ClipBindingConfigurator(state.at),guard=receiverIdentityGuard(config);
      const identity=await config.identity(async live=>{if(await guard(live)===false)throw new DOMException('身份变化','AbortError');});
      if(identity.device_uid===row.device_uid){
        await config.clearBinding(row,guard);
        $('receiver-status').textContent='Server 已解绑，所连 Clip 已确认无上传凭证；Wi-Fi 和录音已保留。交接请联系开发者。';
        await readClip();
      }
    }
    notify('Server 已撤销设备上传权限；云端历史录音保留');
  } finally {state.busy=false;renderControls();}
}
function resetReceiverSetup() {
  clearTimeout(receiverTimer);receiverSetup=new AutomaticClipConfiguration();bindingSetup=new AutomaticClipBinding();
  $('connected-device-uid').textContent='连接后读取设备唯一标识';
  $('receiver-status').textContent='登录并连接 Clip 后自动配置，无需填写设备凭证。';
}
function scheduleReceiverSetup(delay=4000) {
  clearTimeout(receiverTimer);
  receiverTimer=setTimeout(async()=>{
    if(!state.caps||!state.device?.gatt.connected||!state.at||state.at.closed)return;
    if(state.busy||state.authBusy||state.attempt){scheduleReceiverSetup();return;}
    await runClip(configureReceiver).catch(showReceiverError);
  },delay);
}
function showReceiverError(error) {
  if(error.name==='AbortError')return;
  $('receiver-status').textContent=error.message;
  if(['ClipBusyError','ConfigurationChangedError'].includes(error.name))scheduleReceiverSetup();
  else notify(error.message,true);
}
function receiverIdentityGuard(config) {
  const revision=authRevision,client=state.at,device=state.device,owner=state.caps?.user_id;
  const localCurrent=()=>!!owner&&revision===authRevision&&!state.authBusy&&state.caps?.user_id===owner&&config.client===client&&state.at===client&&device===state.device&&device?.gatt.connected&&!client.closed&&!state.attempt;
  return async revalidate=>{
    if(!localCurrent())return false;
    if(revalidate){const current=await (await api('/capabilities',{signal:AbortSignal.timeout(10000)})).json();return localCurrent()&&current.user_id===owner;}
    return true;
  };
}
async function configureReceiver(config) {
  if(state.authBusy){scheduleReceiverSetup();throw new DOMException('等待登录完成','AbortError');}
  if(!state.caps){$('receiver-status').textContent='请先登录，登录后自动配置所连 Clip。';throw Error('请先登录');}
  const owner=state.caps.user_id,isCurrent=receiverIdentityGuard(config);
  $('receiver-status').textContent='正在为当前用户自动配置 Clip…';
  try {
    try {
      const result=await bindingSetup.configure({config:new ClipBindingConfigurator(config.client),owner,isCurrent,
        getProfile:identity=>bindingService.profile(identity),confirm:profile=>bindingService.confirm(profile),
        onIdentity:identity=>{$('connected-device-uid').textContent=`设备 UID：${identity.device_uid}`;}});
      $('receiver-status').textContent=`已覆盖并读回 · ${result.device_name||result.device_id} · 所属用户 ${result.owner_id} · 配置版本 ${result.revision} · ${result.endpoint}`;
      await readClip(config);void ownedDevices.refresh();return result;
    } catch(error) {
      if(error.name!=='UnsupportedBindingError'||!error.legacyAllowed)throw error;
      const result=await receiverSetup.configure({config,owner,isCurrent,getProfile:async device_name=>{
        return bindingRequest('/devices/configuration',{method:'POST',body:{device_name}});
      }});
      $('receiver-status').textContent=result.preserved
        ? '旧固件配置模式：自动上传保持开启，尚不支持连接即覆盖，请先升级 Boa 绑定固件。'
        : `旧固件上传配置已保存 · ${result.device_name} · 完整绑定状态需升级固件后核验`;
      await readClip(config);return result;
    }
  } catch(error) {showReceiverError(error);throw error;}
}
async function attach(device) {
  resetWifiSelection();
  wifiNameEdited=false;
  state.device = device; state.client = null; state.clip = {}; renderClip();
  state.at = await connectAt(device, event => {
    if (state.device !== device) return;
    if (event.event === 'upload') state.clip.upload = event;
    if (event.event === 'wifi_check' && (state.clip.network?.job == null || state.clip.network.job === event.job)) state.clip.network = event;
    renderClip();
  });
  device.addEventListener('gattserverdisconnected', () => {
    if (state.device === device && !device.gatt.connected) { resetReceiverSetup(); $('device-name').textContent = '设备已断开'; $('clip-config-feedback').textContent = '设备已断开；已显示的信息为上次读取，未确认的写入需重连后核实。'; }
    renderClip(); renderControls();
  }, {once:true});
  $('device-name').textContent = device.name || 'Clip';
  $('images').hidden = true;
  await readClip(); renderControls();
}
async function attachFirmware() {
  const reuseConnection = !!state.at && !state.at.closed && state.device.gatt.connected && !state.client;
  if (!reuseConnection) { state.at?.close(); state.at = null; }
  state.client?.close();
  state.client = await connectSmp(state.device, {reuseConnection});
  $('device-name').textContent = state.device.name || 'Clip';
}
async function runClip(task) {
  if (state.busy || state.attempt || !state.at || state.at.closed) throw Error('请先连接 Clip 配置通道，并结束正在进行的操作');
  state.busy = true; renderControls();
  try { await task(new ClipConfigurator(state.at)); }
  finally { state.busy = false; renderReleases(); renderHistory(); renderControls(); }
}
async function endAttempt(attempt) {
  await json(`/upgrades/${attempt.id}`, {state: 'failed', error: '用户结束网页跟踪；设备实际状态未确认'}, 'PATCH');
  if (state.attempt?.id === attempt.id) state.attempt = null;
  $('progress-label').textContent = '已结束记录；设备实际状态仍需核实';
  await refresh(); notify('记录已标记未完成。未向设备发送中断或回滚命令。');
}
action('end-attempt', () => endAttempt(state.attempt));
async function loadIdentity(revision) {
  requireAuthRevision(revision);
  const caps=await json('/capabilities',undefined,'GET');
  if(revision!==authRevision)return;
  state.caps=caps;serverConnection.confirm();await refresh();scheduleReceiverSetup(0);
}
function clearIdentity() {
  ++authRevision;state.authBusy=false;
  state.detachAttempt=true;
  state.caps=null;state.cookieSession=false;state.cookieUser='';state.token='';
  state.releases=[];state.history=[];state.selected=null;
  recordings.reset();ownedDevices.reset();renderReleases();renderHistory();renderControls();
  $('clip-password').value='';resetReceiverSetup();
}
action('login', async () => {
  const revision=++authRevision;state.authBusy=true;renderControls();
  try {
    const user=await webSession.login($('user-id').value);requireAuthRevision(revision);state.token='';state.cookieSession=true;state.cookieUser=user.user_id;
    await loadIdentity(revision);$('user-id').value='';notify('已进入你的工作台');
  } catch(error) {if(revision===authRevision){state.caps=null;state.cookieSession=false;}throw error;}
  finally {if(revision===authRevision)state.authBusy=false;}
});
$('user-id').addEventListener('keydown',event=>{if(event.key==='Enter'&&!state.authBusy)$('login').click();});
action('developer-login', async () => {
  const revision=++authRevision;state.authBusy=true;renderControls();
  try {
    const existing=await webSession.restore();
    requireAuthRevision(revision);
    if(existing)await webSession.logout(existing.user_id);
    requireAuthRevision(revision);
    state.cookieSession=false;state.cookieUser='';state.token=$('token').value.trim();
    const caps=await json('/capabilities',undefined,'GET');requireAuthRevision(revision);state.caps=caps;serverConnection.confirm();await refresh();scheduleReceiverSetup(0);$('token').value='';notify('已登录 Boa Server');
  }
  catch (error) {if(revision===authRevision){state.token='';state.caps=null;}throw error;}
  finally {if(revision===authRevision)state.authBusy=false;}
});
action('logout', async () => {
  const revision=++authRevision;state.authBusy=true;renderControls();
  try {if(state.cookieSession)await webSession.logout(state.cookieUser);}
  catch(error){if(revision===authRevision){state.authBusy=false;if(error.name==='SessionChangedError')clearIdentity();}throw error;}
  requireAuthRevision(revision);state.authBusy=false;
  try { await disconnectGatt(state.device); }
  finally {
    if(revision!==authRevision)return;
    state.at?.close(); state.at = null; state.token = ''; state.caps = null;state.cookieSession=false;state.cookieUser='';
    state.releases = []; state.history = []; state.selected = null; state.clip = {};
    recordings.reset();ownedDevices.reset();
    $('clip-password').value = ''; resetReceiverSetup();
    renderClip(); renderReleases(); renderHistory();
  }
});
action('refresh', refresh);
$('firmware-file').addEventListener('change', () => { $('file-label').textContent = $('firmware-file').files[0]?.name || '选择 MCUboot 固件文件'; renderControls(); });
action('import', async () => {
  const file = $('firmware-file').files[0]; if (!file || file.size > state.caps.max_size_bytes) throw Error('请选择不超过 8 MiB 的 .bin 文件');
  state.busy = true; renderControls();
  try {
    const query = new URLSearchParams({filename: file.name, profile_id: $('profile').value});
    const result = await (await api(`/releases?${query}`, {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file})).json();
    await refresh(); notify(result.verification === 'trusted' ? '导入成功，可信公钥验签通过。可发布此版本。' : '已导入草稿；签名未通过，不能发布或升级。');
  } finally { state.busy = false; renderReleases(); renderControls(); }
});
async function chooseClip(reuseAuthorized = false) {
  if (state.busy) return;
  state.busy = true; renderControls();
  try {
    const existing = reuseAuthorized ? await grantedClip(navigator.bluetooth) : null;
    const device = existing || await navigator.bluetooth.requestDevice({filters: [{namePrefix: 'Clip'}, {namePrefix: 'CLIP'}, {namePrefix: 'reSpeaker'}], optionalServices: [AT_SERVICE,...SMP_SERVICES]});
    if (state.device && state.device.id !== device.id) {
      for (const id of ['clip-ssid']) $(id).value = '';
    }
    await disconnectGatt(state.device);
    state.at?.close(); state.at = null;
    await attach(device);
    await configureReceiver(new ClipConfigurator(state.at)).catch(showReceiverError);
    notify('已连接 Clip，并读取支持的设备配置');
  } finally { state.busy = false; renderReleases(); renderHistory(); renderControls(); }
}
action('connect-device', chooseClip);
action('config-connect', () => chooseClip(true));
action('config-refresh', () => runClip(async config => { await configureReceiver(config); await readClip(config); $('clip-config-feedback').textContent = '已重新读取设备状态；未知或不支持的项目保持未知。'; }));
function editWifi() {
  wifiEdited=true; wifiNameEdited=true; renderClip();
}
function resetWifiSelection() {
  wifiEdited=true;
}
$('clip-ssid').addEventListener('input',()=>{
  editWifi();
});
$('clip-password').addEventListener('input',()=>{wifiEdited=true; renderClip();});
$('toggle-wifi-password').addEventListener('click',()=>toggleWifiPassword($('clip-password'),$('toggle-wifi-password')));
action('save-wifi', async () => {
    await runClip(async config => {
      wifiEdited=true; state.clip.network=null; renderClip();
      $('clip-config-feedback').textContent='正在保存并测试 Clip 连接；若设备正在录音或上传，请等待结束后重试。';
      await config.saveAndCheckWifi($('clip-ssid').value,$('clip-password').value,row=>{
        wifiEdited=false; state.clip.network=row; renderClip();
      },{onSaved:saved=>{state.clip.wifi=saved; renderClip(); $('clip-config-feedback').textContent='Clip 已确认保存 Wi-Fi，正在测试实际连接…';}});
      await readClip(config);
      $('clip-config-feedback').textContent = 'Wi-Fi 已保存，Clip 已通过连接与 DHCP 测试。Server 上传结果请在“我的录音”核实。';
    });
});
action('configure-receiver', () => runClip(configureReceiver));
action('check-wifi', () => runClip(async config => {
  if(wifiEdited && $('clip-ssid').value!==decodeSsid(state.clip.wifi?.ssid_hex||'')) throw Error('网络名称已修改，请先点“保存并测试连接”；单独测试使用 Clip 已保存的配置。');
  await config.checkNetwork(row => { wifiEdited=false; state.clip.network = row; renderClip(); });
  $('clip-config-feedback').textContent = 'Wi-Fi 与 DHCP 已通过，尚未验证 Server。上传完成需以 Server 文件和整文件校验为准。';
}));
for (const [id, enabled] of [['auto-on',true],['auto-off',false]]) action(id, () => runClip(async config => {
  if(enabled)await configureReceiver(config);
  state.clip.automatic = await config.automatic(enabled,receiverIdentityGuard(config)); renderClip();
  if(!enabled)scheduleReceiverSetup(0);
  $('clip-config-feedback').textContent = enabled ? '设备确认自动上传已开启；实际上传结果请查看持久确认字节与 Server 文件。' : '设备确认自动上传已关闭，当前自动任务可能需要时间退出。';
}));
$('compatible').addEventListener('change', renderControls);
async function disconnectClip() {
  try { await disconnectGatt(state.device); }
  finally { state.at?.close(); resetReceiverSetup(); renderClip(); }
}
action('disconnect', disconnectClip);
action('config-disconnect', disconnectClip);
action('upgrade', async () => {
  if ($('upgrade').disabled) return;
  state.busy = true; renderControls();
  try {
    const bytes = new Uint8Array(await (await api(`/releases/${state.selected.id}/content`)).arrayBuffer());
    state.attempt = await json('/upgrades', {release_id: state.selected.id, device_label: state.device.name || 'Clip'});
    await attachFirmware();
    $('progress-label').textContent = '正在上传至设备备用槽…';
    await new FirmwareUpdater(state.client).upload(bytes, state.selected, value => { $('progress').value = value; $('progress-label').textContent = `上传 ${Math.floor(value * 100)}% · 尚未确认安装`; }, async () => {
      state.attempt = await json(`/upgrades/${state.attempt.id}`, {state: 'awaiting_reconnect'}, 'PATCH');
    }, async () => {
      if (!state.at || state.at.closed) throw Error('升级保活通道已断开，请重新连接 Clip');
      await state.at.send('AT+VERSION');
    });
    $('progress-label').textContent = '已请求启动目标镜像，请重连核实版本';
    notify('设备需要重启。请点击“重连并核实目标版本”，确认后才算升级成功。');
  } catch (error) {
    if (state.attempt?.state === 'awaiting_reconnect') {
      $('progress-label').textContent = '设备状态待核实，请重连检查';
      throw error;
    }
    $('progress-label').textContent = `升级未完成：${error.message}`;
    if (state.attempt) {
      try { await json(`/upgrades/${state.attempt.id}`, {state: 'failed', error: error.message.slice(0, 240)}, 'PATCH'); } catch (_) { notify('服务端记录未更新，请刷新后核实', true); }
    }
    state.client?.close();
    await disconnectGatt(state.device).catch(() => {});
    state.attempt = null; throw error;
  } finally { state.busy = false; await refresh(); }
});
action('verify', async () => {
  if (!state.device || !state.attempt) throw Error('请先选择对应 Clip');
  state.busy = true; renderControls();
  try {
    await attachFirmware();
    const result = await new FirmwareUpdater(state.client).confirm({image_hash: state.attempt.expected_image_hash});
    await json(`/upgrades/${state.attempt.id}`, result, 'PATCH');
    state.attempt = null; $('progress-label').textContent = '目标镜像已运行并确认'; notify('已核实：升级成功');
  } finally { state.busy = false; await refresh(); }
});
window.addEventListener('beforeunload', event => { if (state.busy || state.attempt) { event.preventDefault(); event.returnValue = ''; } });
$('endpoint').textContent = location.origin;
$('bluetooth-support').textContent = navigator.bluetooth && window.isSecureContext ? '浏览器提供 Web Bluetooth，连接时需授权。' : '当前浏览器未提供 Web Bluetooth；请使用 Mac / Android Chrome。';
function renderNavigation() {
  const target = location.hash || '#clip-config';
  document.querySelectorAll('.sidebar .nav').forEach(item => item.classList.toggle('active',item.getAttribute('href') === target));
}
window.addEventListener('hashchange',renderNavigation);
renderNavigation(); renderClip(); renderControls();
action('server-retry', () => serverConnection.connect());
window.addEventListener('online', () => { void serverConnection.connect(); });
void serverConnection.connect();
async function restoreLogin() {
  const revision=++authRevision;state.authBusy=true;renderControls();
  try {
    const user=await webSession.restore();
    if(revision!==authRevision)return;
    if(user){state.cookieSession=true;state.cookieUser=user.user_id;await loadIdentity(revision);}
  } catch (_) {
    if(revision===authRevision){state.cookieSession=false;state.caps=null;notify('登录状态未能恢复，请输入用户 ID 重新进入',true);}
  } finally {if(revision===authRevision){state.authBusy=false;renderControls();}}
}
void restoreLogin();
