import test from 'node:test';
import assert from 'node:assert/strict';
import {mountOwnedDevices} from '../owned-devices.mjs';

class Element {
  constructor(){this.children=[];this.textContent='';this.listeners={};this.disabled=false;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];this.textContent='';}
  addEventListener(name,callback){this.listeners[name]=callback;}
}
function page(){
  const nodes=new Map([['owned-devices',new Element()],['owned-devices-status',new Element()]]);
  globalThis.document={getElementById:id=>nodes.get(id),createElement:()=>new Element()};return nodes;
}
const row={device_id:'clip01',device_name:'Clip',device_uid:'a'.repeat(16),binding_id:'b'.repeat(32),epoch:1,revision:1,provisioning_state:'revoked',device_cleanup_pending:true};

test('offline revoked device offers a local cleanup retry instead of a permanently disabled action',async()=>{
  const nodes=page();let selected;
  const view=mountOwnedDevices({session:()=>({key:'alice:1'}),service:{devices:async()=>[row]},notify:()=>{},onUnbind:async value=>selected=value});
  await view.refresh();const button=nodes.get('owned-devices').children[0].children[1];
  assert.equal(button.disabled,false);assert.equal(button.textContent,'清理设备');
  await button.listeners.click();assert.equal(selected.binding_id,row.binding_id);
});
test('logout cancels a pending device list before it can display the old user data',async()=>{
  const nodes=page();let identity={key:'alice:1'},resolve;
  const view=mountOwnedDevices({session:()=>identity,service:{devices:()=>new Promise(done=>resolve=done)},notify:()=>{},onUnbind:async()=>{}});
  const pending=view.refresh();identity=null;view.reset();resolve([row]);await pending;
  assert.equal(nodes.get('owned-devices').children.length,0);
  assert.equal(nodes.get('owned-devices-status').textContent,'登录后查看已分配设备。');
});
test('completed developer cleanup has no active clear action and list rendering excludes token fields',async()=>{
  const nodes=page();const secret='synthetic-token-not-for-display';
  const view=mountOwnedDevices({session:()=>({key:'alice:1'}),service:{devices:async()=>[{...row,device_cleanup_pending:false,device_token:secret}]},notify:()=>{},onUnbind:async()=>{}});
  await view.refresh();assert.equal(nodes.get('owned-devices').children[0].children[1].disabled,true);
  const text=value=>value.textContent+value.children.map(text).join('');assert.ok(!text(nodes.get('owned-devices')).includes(secret));
});
