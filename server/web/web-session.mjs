// The browser keeps an HttpOnly session cookie; JavaScript never receives it.
export class WebSession {
  constructor({fetcher=fetch,timeoutMs=10000}={}) {this.fetcher=fetcher;this.timeoutMs=timeoutMs;}
  async request(method,body,userId) {
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),this.timeoutMs);
    try {
      const fetcher=this.fetcher;
      const response=await fetcher('/api/boa/v1/session',{
        method,credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal,
        headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(userId?{'X-Boa-User':userId}:{})},
        ...(body===undefined?{}:{body:JSON.stringify(body)}),
      });
      if(method==='GET'&&response.status===401)return null;
      if(!response.ok){
        const value=await response.json().catch(()=>({}));
        if(response.status===409&&value.detail==='session_user_changed'){const error=Error('登录用户已在其他页面切换，请重新进入');error.name='SessionChangedError';throw error;}
        throw Error(`${typeof value.detail==='string'?value.detail:'登录请求失败'}（HTTP ${response.status}）`);
      }
      if(method==='DELETE')return null;
      const value=await response.json();
      if(!/^[A-Za-z0-9_-]{1,32}$/.test(value.user_id||'')||value.role!=='user')throw Error('服务端登录身份无效');
      return value;
    } finally {clearTimeout(timer);}
  }
  async login(id) {
    id=id.trim();if(!/^[A-Za-z0-9_-]{1,32}$/.test(id))throw Error('用户 ID 需为 1–32 位字母、数字、下划线或短横线');
    const value=await this.request('POST',{user_id:id});
    if(value.user_id!==id)throw Error('服务端返回身份与登录用户不一致');
    return value;
  }
  restore() {return this.request('GET');}
  logout(userId) {return this.request('DELETE',undefined,userId);}
}
