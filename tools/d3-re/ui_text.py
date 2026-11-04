"""Verified UTF-8 text slot shared by UI labels and text-button subclasses.

Other UI classes do not necessarily own a string at +0x398. Do not guess an
encoding: 0x83AD9D0 uses strlen, byte allocation, strb and a byte-string copy
for +0x398. Live label bytes independently confirm UTF-8, including Chinese.
"""

JS = r"""
const UI_TEXT_VTABLES=new Set([0x90ae520,0x90abb48]);
function readUIText(p,capacity){
  const value={text:null,encoding:'utf-8',capacity};
  if(p<0x130000000||p>=0x180000000||capacity<1||capacity>0x100000)
    return {...value,error:'invalid text buffer/capacity'};
  try{
    const bytes=new Uint8Array(gm.add(p).readByteArray(Math.min(capacity,4096))),n=bytes.indexOf(0);
    value.raw=Array.from(bytes.slice(0,n<0?128:Math.min(n,128)),b=>b.toString(16).padStart(2,'0')).join('');
    if(n<0)return {...value,error:'unterminated or truncated UTF-8'};
    if(!n)return value;
    const text=gm.add(p).readUtf8String(n);
    if(/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd\ufffe\uffff]/.test(text))
      return {...value,error:'invalid UTF-8/control characters'};
    return {...value,text};
  }
  catch(e){return {...value,error:e.message};}
}
"""
