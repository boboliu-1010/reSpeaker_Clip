// Service reachability is independent of user login and Clip connectivity.
export class ServerConnection {
  constructor({fetcher=fetch,onChange=()=>{},timeoutMs=8000}={}) {
    this.fetcher=fetcher;this.onChange=onChange;this.timeoutMs=timeoutMs;
    this.status='connecting';this.revision=0;this.controller=null;
  }
  update(status) { this.status=status;this.onChange(status); }
  confirm() {
    this.revision++;this.controller?.abort();this.update('online');
  }
  async connect() {
    const revision=++this.revision;
    this.controller?.abort();const controller=new AbortController();this.controller=controller;
    this.update('connecting');let timer;
    try {
      const request=async()=>{
        const fetcher=this.fetcher;
        const response=await fetcher('/api/boa/v1/health',{
          signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error',
        });
        if(!response.ok)throw Error('Server unavailable');
        const body=await response.json();
        if(body?.service!=='boa'||body?.status!=='ok')throw Error('Unexpected Server response');
      };
      await Promise.race([request(),new Promise((_,reject)=>{
        timer=setTimeout(()=>{controller.abort();reject(Error('Server timeout'));},this.timeoutMs);
      })]);
      if(revision===this.revision)this.update('online');
    } catch (_) { if(revision===this.revision)this.update('offline'); }
    finally { clearTimeout(timer); }
    return this.status;
  }
}
