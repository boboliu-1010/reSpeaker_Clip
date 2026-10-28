import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Execute the real renderControls, with only its DOM/environment boundary stubbed.
const source=readFileSync(new URL('../app.mjs',import.meta.url),'utf8');
test('editing names and reconnecting keep the password typed in this page',()=>{
  const nodes=new Map(); const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',replaceChildren(){}});return nodes.get(id);};
  $('clip-password').value='synthetic-test-only';
  const start=source.indexOf('function editWifi()');
  const end=source.indexOf("$('clip-ssid').addEventListener",start);
  const context=vm.createContext({$,wifiEdited:false,wifiNameEdited:false,state:{clip:{}},renderClip(){},Option:class{}});
  vm.runInContext(source.slice(start,end)+'\neditWifi(); resetWifiSelection();',context);
  assert.equal($('clip-password').value,'synthetic-test-only');
});

test('the save action retains typed password after both successful and failed tests',async()=>{
  const start=source.indexOf("action('save-wifi',"); const end=source.indexOf("action('configure-receiver',",start);
  assert.ok(start >= 0 && end > start);
  for(const failed of [false,true]) {
    const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{value:''});return nodes.get(id);};
    $('clip-password').value='synthetic-test-only';$('clip-ssid').value='Clip-Net';
    let save;
    const context=vm.createContext({$,wifiEdited:false,state:{clip:{}},renderClip(){},readClip:async()=>{},
      action:(id,callback)=>save=callback,runClip:async callback=>callback({saveAndCheckWifi:async()=>{if(failed)throw Error('connection failed');}})});
    vm.runInContext(source.slice(start,end),context);
    if(failed)await assert.rejects(save());else await save();
    assert.equal($('clip-password').value,'synthetic-test-only');
  }
});
