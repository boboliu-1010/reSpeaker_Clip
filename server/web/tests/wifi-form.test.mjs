import test from 'node:test';
import assert from 'node:assert/strict';
import * as form from '../wifi-form.mjs';

const clip={wifi:{configured:true,saved:true,ssid_hex:'436c69702d4e6574'},network:{state:'succeeded',ip:'192.168.1.8',cleanup_error:0},upload:{active:false,stage:'succeeded'}};
test('Clip SSID is separate from Mac and a past DHCP success is not a current connection',()=>{
  const view=form.clipWifiView(clip,{connected:true});
  assert.equal(view.ssid,'Clip-Net');
  assert.match(view.connection,/实时.*未知|未回报/);
  assert.match(view.test,/最近.*通过/);
  assert.doesNotMatch(view.connection,/已连接/);
});
test('a disconnected Clip never displays cached upload phase as live Wi-Fi',()=>{
  const view=form.clipWifiView({...clip,upload:{active:true,stage:'sending'}},{connected:false});
  assert.equal(view.ssid,'Clip-Net'); assert.match(view.connection,/断开|上次/);
  assert.doesNotMatch(view.connection,/正在上传/);
});
test('active device upload and connection phases are displayed without inventing a live SSID',()=>{
  assert.match(form.clipWifiView({...clip,upload:{active:true,stage:'connecting'}},{connected:true}).connection,/正在连接/);
  assert.match(form.clipWifiView({...clip,upload:{active:true,stage:'sending'}},{connected:true}).connection,/正在上传/);
  assert.equal(form.clipWifiView({wifi:{configured:false}},{connected:true}).ssid,'');
});
test('Clip read fills device name while ordinary refresh preserves an edited draft',()=>{
  assert.equal(form.wifiNameFromDevice('Mac-Net',clip.wifi,{force:true}), 'Clip-Net');
  assert.equal(form.wifiNameFromDevice('Manual-Net',clip.wifi,{edited:true}), 'Manual-Net');
  assert.equal(form.wifiNameFromDevice('Mac-Net',clip.wifi), 'Clip-Net');
});
test('show and hide change input type and accessibility state while preserving password',()=>{
  const input={type:'password',value:'synthetic-test-only'};
  const attributes={};const button={textContent:'显示密码',setAttribute:(k,v)=>attributes[k]=v};
  form.toggleWifiPassword(input,button);
  assert.equal(input.type,'text'); assert.equal(input.value,'synthetic-test-only');
  assert.equal(attributes['aria-pressed'],'true'); assert.equal(button.textContent,'隐藏密码');
  form.toggleWifiPassword(input,button);
  assert.equal(input.type,'password'); assert.equal(input.value,'synthetic-test-only');
  assert.equal(attributes['aria-pressed'],'false');
});
