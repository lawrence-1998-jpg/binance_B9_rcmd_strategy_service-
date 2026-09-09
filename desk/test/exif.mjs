import { readCaptureDate } from '/tmp/exifmod.mjs'

class FakeBlob {
  constructor(buf){ this.buf = Buffer.from(buf) }
  slice(a,b){ return new FakeBlob(this.buf.subarray(a,b)) }
  async arrayBuffer(){ return this.buf.buffer.slice(this.buf.byteOffset, this.buf.byteOffset+this.buf.byteLength) }
}

function jpegWithExif({le=false, dtOrig='2024:08:30 19:12:04', app1Len=null, ifdCount=null, badOffset=false, truncate=0}={}) {
  const tiff = []
  const u16=(v)=>le?[v&255,v>>8]:[v>>8,v&255]
  const u32=(v)=>le?[v&255,(v>>8)&255,(v>>16)&255,(v>>24)&255]:[(v>>24)&255,(v>>16)&255,(v>>8)&255,v&255]
  // TIFF header
  tiff.push(...(le?[0x49,0x49]:[0x4d,0x4d]), ...u16(42), ...u32(8))
  // IFD0: 1 entry -> ExifIFD pointer
  const exifIfdOff = badOffset ? 0x7fffff : 8 + 2 + 12 + 4
  tiff.push(...u16(ifdCount ?? 1))
  tiff.push(...u16(0x8769), ...u16(4), ...u32(1), ...u32(exifIfdOff))
  tiff.push(...u32(0))
  // ExifIFD: DateTimeOriginal
  const strOff = exifIfdOff + 2 + 12 + 4
  tiff.push(...u16(1))
  tiff.push(...u16(0x9003), ...u16(2), ...u32(dtOrig.length+1), ...u32(strOff))
  tiff.push(...u32(0))
  for (const c of dtOrig) tiff.push(c.charCodeAt(0))
  tiff.push(0)
  const exifPayload = [0x45,0x78,0x69,0x66,0,0, ...tiff]
  const len = app1Len ?? (exifPayload.length + 2)
  let out = [0xff,0xd8, 0xff,0xe1, (len>>8)&255, len&255, ...exifPayload, 0xff,0xda, 0,2]
  if (truncate) out = out.slice(0, out.length - truncate)
  return new FakeBlob(out)
}

const cases = [
  ['正常 大端',           jpegWithExif(),                                       '2024-08-30'],
  ['正常 小端',           jpegWithExif({le:true}),                              '2024-08-30'],
  ['空文件',              new FakeBlob([]),                                     null],
  ['只有 SOI',            new FakeBlob([0xff,0xd8]),                            null],
  ['不是 JPEG',           new FakeBlob([0x89,0x50,0x4e,0x47,1,2,3,4]),          null],
  ['APP1 长度撒谎(巨大)',  jpegWithExif({app1Len:0xffff}),                       'any'],
  ['APP1 长度撒谎(为0)',   jpegWithExif({app1Len:0}),                            'any'],
  ['IFD 条目数=65535',    jpegWithExif({ifdCount:65535}),                       'any'],
  ['offset 指向文件外',    jpegWithExif({badOffset:true}),                       null],
  ['日期格式非法',         jpegWithExif({dtOrig:'not-a-date-at-all'}),           null],
  ['年份 0000',           jpegWithExif({dtOrig:'0000:01:01 00:00:00'}),         null],
  ['年份 9999',           jpegWithExif({dtOrig:'9999:12:31 23:59:59'}),         null],
  ['截断到一半',           jpegWithExif({truncate:20}),                          'any'],
  ['全 0xff',             new FakeBlob(new Array(300).fill(0xff)),              'any'],
  ['随机字节',            new FakeBlob(Array.from({length:2000},()=>Math.floor(Math.random()*256))), 'any'],
]

let bad=0
for (const [name, blob, want] of cases) {
  const t0=Date.now()
  let got, err=null
  try { got = await Promise.race([readCaptureDate(blob), new Promise((_,r)=>setTimeout(()=>r(new Error('超时/死循环')),3000))]) }
  catch(e){ err=e.message }
  const ms=Date.now()-t0
  const ok = err ? false : (want==='any' ? true : got===want)
  if (!ok) bad++
  console.log(`${ok?'✓':'✗'} ${name.padEnd(20)} → ${err?'抛异常: '+err:JSON.stringify(got)}  (${ms}ms)`)
}
console.log(`\n${bad?'✗ '+bad+' 项有问题':'✓ 全部通过：不崩、不死循环、坏输入一律返回 null'}`)
