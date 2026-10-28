import test from 'node:test';
import assert from 'node:assert/strict';
import {wrapClipOpus, oggCrc, MAX_CLIP_BYTES} from '../clip-audio.mjs';

const raw = (...packets) => Uint8Array.from(packets.flatMap(p => [p.length & 255, p.length >>> 8, ...p]));
function pages(bytes) {
  const rows=[];
  for(let offset=0;offset<bytes.length;) {
    assert.equal(new TextDecoder().decode(bytes.subarray(offset,offset+4)),'OggS');
    const view=new DataView(bytes.buffer,bytes.byteOffset+offset),count=bytes[offset+26];
    const lace=bytes.slice(offset+27,offset+27+count),size=lace.reduce((a,b)=>a+b,0);
    rows.push({flags:bytes[offset+5],granule:view.getBigUint64(6,true),sequence:view.getUint32(18,true),
      payload:bytes.slice(offset+27+count,offset+27+count+size),lace});
    offset+=27+count+size;
  }
  return rows;
}
test('Ogg CRC matches the independent CRC-32/MPEG-2 init-zero check vector',()=>{
  assert.equal(oggCrc(new TextEncoder().encode('123456789')),0x89a1897f);
});
test('raw frames become lossless Ogg packets with proper headers and sample positions',()=>{
  const a=[0xf8,11,22],b=[0xf8,33,44],result=wrapClipOpus(raw(a,b)),p=pages(result.bytes);
  assert.equal(result.duration,.04);assert.equal(result.channels,1);assert.equal(result.packets,2);
  assert.equal(new TextDecoder().decode(p[0].payload.subarray(0,8)),'OpusHead');
  assert.equal(p[0].payload[9],1);assert.equal(p[0].flags,2);
  assert.equal(new TextDecoder().decode(p[1].payload.subarray(0,8)),'OpusTags');
  assert.deepEqual([...p[2].payload],a);assert.deepEqual([...p[3].payload],b);
  assert.equal(p[2].granule,960n);assert.equal(p[3].granule,1920n);assert.equal(p[3].flags,4);
  assert.deepEqual(p.map(x=>x.sequence),[0,1,2,3]);
});
test('duration is read from TOC and stereo packets preserve two output channels',()=>{
  const result=wrapClipOpus(raw([0x80,7],[0xfc,9]));
  assert.equal(result.duration,.0225);assert.equal(result.channels,2);
  assert.equal(pages(result.bytes)[0].payload[9],2);
});
test('packet sizes divisible by 255 terminate lacing explicitly',()=>{
  const packet=new Array(255).fill(0);packet[0]=0xf8;
  const p=pages(wrapClipOpus(raw(packet)).bytes).at(-1);
  assert.deepEqual([...p.lace],[255,0]);assert.equal(p.payload.length,255);
});
test('large length-prefixed packet spans pages without losing bytes',()=>{
  // 48 * 2.5 ms CBR frames, 1,200 bytes each, plus valid code-3 padding.
  const packet=[0x83,0x70,...Array(31).fill(255),27,...Array(57600+7901).fill(7)];
  assert.equal(packet.length,65535);
  const p=pages(wrapClipOpus(raw(packet)).bytes).slice(2);
  assert.equal(p.length,2);assert.equal(p[0].granule,0xffffffffffffffffn);
  assert.equal(p[1].flags,5);assert.equal(p[1].granule,5760n);
  assert.deepEqual([...p[0].payload,...p[1].payload],packet);
});
test('malformed CBR, VBR, padding and oversized individual frames are rejected',()=>{
  const invalid=[[0xf9,1],[0xfa],[0xfa,255],[0xfb,0x41],
    [0xfb,0x82,255],[0xfb,0x42,20,1],[0xf8,...Array(1276).fill(0)]];
  for(const packet of invalid)assert.throws(()=>wrapClipOpus(raw(packet)),/Opus/);
});
test('zero-byte DTX frames remain permitted by Opus framing',()=>{
  assert.equal(wrapClipOpus(raw([0xfb,0x81])).duration,.02);
});
test('empty, truncated, zero-length and invalid-duration streams fail closed',()=>{
  for(const input of [new Uint8Array(),Uint8Array.of(1),Uint8Array.of(3,0,0xf8),raw([]),raw([0xfb]),raw([0xfb,0]),raw([0xfb,7])]) {
    assert.throws(()=>wrapClipOpus(input));
  }
});
test('oversized streams are rejected before parsing',()=>{
  assert.throws(()=>wrapClipOpus(new Uint8Array(MAX_CLIP_BYTES+1)),/8 MiB/);
});
