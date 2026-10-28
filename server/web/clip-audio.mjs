// Clip stores uint16 little-endian packet length followed by a raw Opus packet.
// Only the container changes here. Chrome performs the actual Opus decoding.
export const MAX_CLIP_BYTES = 8 * 1024 * 1024;
const MAX_PACKETS = 180000, MAX_SAMPLES = 48000 * 3600;
const encoder = new TextEncoder();
const crcTable = Uint32Array.from({length:256},(_,value)=>{
  let crc=value<<24;
  for(let bit=0;bit<8;bit++) crc=(crc<<1)^((crc&0x80000000)?0x04c11db7:0);
  return crc>>>0;
});
export function oggCrc(bytes) {
  let crc=0;
  for(const value of bytes) crc=((crc<<8)^crcTable[((crc>>>24)^value)&255])>>>0;
  return crc;
}
function samplesInPacket(packet) {
  const config=packet[0]>>>3,code=packet[0]&3;
  const frame=config>=16 ? 120<<(config&3) : config>=12 ? 480<<(config&1) : [480,960,1920,2880][config&3];
  if(code===3 && packet.length<2) throw Error('Opus 帧头已截断');
  const count=code===0 ? 1 : code===3 ? packet[1]&63 : 2;
  if(!count || count>48 || frame*count>5760) throw Error('Opus 帧时长无效');
  let offset=code===3?2:1,end=packet.length;
  const invalid=()=>{throw Error('Opus 帧长度、填充或打包格式无效');};
  const frameSize=()=>{
    if(offset>=end) return invalid();
    const first=packet[offset++];
    if(first<252)return first;
    if(offset>=end)return invalid();
    return first+4*packet[offset++];
  };
  if(code===3 && packet[1]&64) {
    let padding=0,value;
    do {if(offset>=end)return invalid();value=packet[offset++];padding+=value===255?254:value;}while(value===255);
    end-=padding;if(end<offset)return invalid();
  }
  if(code===2 || (code===3 && packet[1]&128)) {
    let total=0;
    for(let i=0;i<count-1;i++) {total+=frameSize();if(total>end-offset)return invalid();}
    const last=end-offset-total;if(last<0 || last>1275)return invalid();
  } else if((end-offset)%count || (end-offset)/count>1275) return invalid();
  return frame*count;
}
function page(payload,lace,flags,granule,sequence) {
  const bytes=new Uint8Array(27+lace.length+payload.length),view=new DataView(bytes.buffer);
  bytes.set(encoder.encode('OggS'));bytes[5]=flags;
  view.setBigUint64(6,BigInt.asUintN(64,granule),true);
  view.setUint32(14,0x424f4101,true);view.setUint32(18,sequence,true);
  bytes[26]=lace.length;bytes.set(lace,27);bytes.set(payload,27+lace.length);
  view.setUint32(22,oggCrc(bytes),true);
  return bytes;
}
export function wrapClipOpus(raw) {
  if(!(raw instanceof Uint8Array) || !raw.length) throw Error('Clip 录音为空');
  if(raw.length>MAX_CLIP_BYTES) throw Error('Clip 单段播放上限为 8 MiB');
  const packets=[];let offset=0,samples=0,channels=1;
  while(offset<raw.length) {
    if(offset+2>raw.length) throw Error('Clip 帧长度已截断');
    const length=raw[offset]|(raw[offset+1]<<8);offset+=2;
    if(!length || offset+length>raw.length) throw Error('Clip 音频帧为空或已截断');
    const packet=raw.subarray(offset,offset+length),duration=samplesInPacket(packet);
    samples+=duration;
    if(packets.length>=MAX_PACKETS || samples>MAX_SAMPLES) throw Error('Clip 录音帧数或时长超过播放上限');
    if(packet[0]&4) channels=2;
    packets.push({packet,duration});offset+=length;
  }
  const head=new Uint8Array(19),headView=new DataView(head.buffer);
  head.set(encoder.encode('OpusHead'));head[8]=1;head[9]=channels;
  // Raw Clip has no encoder pre-skip metadata; retain all decoded samples.
  headView.setUint16(10,0,true);headView.setUint32(12,16000,true);
  const vendor=encoder.encode('Boa Voice'),tags=new Uint8Array(16+vendor.length),tagsView=new DataView(tags.buffer);
  tags.set(encoder.encode('OpusTags'));tagsView.setUint32(8,vendor.length,true);tags.set(vendor,12);
  const chunks=[page(head,[head.length],2,0n,0),page(tags,[tags.length],0,0n,1)];
  let sequence=2,granule=0n;
  packets.forEach(({packet,duration},packetIndex)=>{
    const lace=Array(Math.floor(packet.length/255)).fill(255);lace.push(packet.length%255);
    let consumed=0;
    for(let index=0;index<lace.length;index+=255) {
      const part=lace.slice(index,index+255),size=part.reduce((a,b)=>a+b,0),complete=index+255>=lace.length;
      if(complete) granule+=BigInt(duration);
      const flags=(index?1:0)|(complete && packetIndex===packets.length-1?4:0);
      chunks.push(page(packet.subarray(consumed,consumed+size),part,flags,complete?granule:-1n,sequence++));
      consumed+=size;
    }
  });
  const bytes=new Uint8Array(chunks.reduce((sum,chunk)=>sum+chunk.length,0));offset=0;
  for(const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.length;}
  return {bytes,duration:samples/48000,channels,packets:packets.length};
}
