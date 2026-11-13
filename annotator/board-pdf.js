/* A self-contained raster PDF: Cyrillic uses the browser's system font, no external fonts. */
(() => {
  const arrow = d => { const a=Math.atan2(d.h,d.w),n=14; return [[d.x+d.w-n*Math.cos(a-.5),d.y+d.h-n*Math.sin(a-.5)],[d.x+d.w,d.y+d.h],[d.x+d.w-n*Math.cos(a+.5),d.y+d.h-n*Math.sin(a+.5)]]; };
  const measure = document.createElement('canvas').getContext('2d'); measure.font='20px sans-serif';
  function textLines(text) {
    const lines = [];
    for (const paragraph of text.split('\n')) {
      let line = '';
      for (const word of paragraph.match(/\s+|\S+/gu) || []) {
        if (line && measure.measureText(line + word).width > 600) {
          lines.push(line);
          line = '';
        }
        if (measure.measureText(word).width <= 600) {
          line += word;
          continue;
        }
        for (const char of word) {
          if (line && measure.measureText(line + char).width > 600) {
            lines.push(line);
            line = '';
          }
          line += char;
        }
      }
      lines.push(line);
    }
    return lines;
  }
  function bounds(d) {
    let xs=[d.x],ys=[d.y];
    if(d.kind==='pen'){xs=d.points.map(p=>d.x+p[0]);ys=d.points.map(p=>d.y+p[1]);}
    else if(d.kind==='text'){const lines=textLines(d.text);xs.push(d.x+lines.reduce((width,line)=>Math.max(width,measure.measureText(line).width),1));ys.push(d.y+lines.length*26);}
    else {xs.push(d.x+d.w);ys.push(d.y+d.h);if(d.kind==='arrow')for(const p of arrow(d)){xs.push(p[0]);ys.push(p[1]);}}
    const pad=Math.max(d.width,4);return {x:Math.min(...xs)-pad,y:Math.min(...ys)-pad,w:Math.max(...xs)-Math.min(...xs)+pad*2,h:Math.max(...ys)-Math.min(...ys)+pad*2};
  }
  function paint(ctx,d){ctx.strokeStyle=d.color;ctx.fillStyle=d.color;ctx.lineWidth=d.width;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();
    if(d.kind==='pen'){d.points.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](d.x+p[0],d.y+p[1]));ctx.stroke();}
    if(d.kind==='rect')ctx.strokeRect(d.x,d.y,d.w,d.h);
    if(d.kind==='ellipse'){ctx.ellipse(d.x+d.w/2,d.y+d.h/2,Math.max(d.w/2,.1),Math.max(d.h/2,.1),0,0,Math.PI*2);ctx.stroke();}
    if(d.kind==='arrow'){ctx.moveTo(d.x,d.y);ctx.lineTo(d.x+d.w,d.y+d.h);ctx.stroke();ctx.beginPath();arrow(d).forEach((p,i)=>ctx[i?'lineTo':'moveTo'](...p));ctx.stroke();}
    if(d.kind==='text'){ctx.font='20px sans-serif';ctx.textBaseline='top';textLines(d.text).forEach((s,i)=>ctx.fillText(s,d.x,d.y+i*26));}
  }
  async function download(items,title){
    const data=items.map(i=>i.data).filter(Boolean),bs=data.map(bounds);
    const x=Math.min(0,...bs.map(b=>b.x)),y=Math.min(0,...bs.map(b=>b.y));
    // Export the content, not the current viewport. Empty boards use a sheet-sized area.
    const left=bs.length?Math.min(...bs.map(b=>b.x))-30:x,top=bs.length?Math.min(...bs.map(b=>b.y))-30:y;
    const w=bs.length?Math.max(...bs.map(b=>b.x+b.w))-left+30:1120,h=bs.length?Math.max(...bs.map(b=>b.y+b.h))-top+30:790;
    const scale=Math.min(2,4096/Math.max(w,h));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.ceil(w*scale));canvas.height=Math.max(1,Math.ceil(h*scale));
    const ctx=canvas.getContext('2d');ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.scale(scale,scale);ctx.translate(-left,-top);data.forEach(d=>paint(ctx,d));
    const jpeg=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.94));if(!jpeg)throw Error('Не удалось создать PDF.');const pixels=new Uint8Array(await jpeg.arrayBuffer());
    const pw=w>=h?1190:842,ph=w>=h?842:1190,k=Math.min((pw-48)/canvas.width,(ph-48)/canvas.height),iw=canvas.width*k,ih=canvas.height*k;
    const stream=`q ${iw} 0 0 ${ih} ${(pw-iw)/2} ${(ph-ih)/2} cm /Im0 Do Q\n`;
    const enc=new TextEncoder(),chunks=[],offsets=[0];let length=0;
    const add=s=>{const b=typeof s==='string'?enc.encode(s):s;chunks.push(b);length+=b.length;};
    add('%PDF-1.4\n');const obj=(n,s)=>{offsets[n]=length;add(`${n} 0 obj\n${s}\nendobj\n`);};
    obj(1,'<< /Type /Catalog /Pages 2 0 R >>');obj(2,'<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
    obj(3,`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`);
    offsets[4]=length;add(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${pixels.length} >>\nstream\n`);add(pixels);add('\nendstream\nendobj\n');obj(5,`<< /Length ${enc.encode(stream).length} >>\nstream\n${stream}endstream`);
    const start=length;add('xref\n0 6\n0000000000 65535 f \n');for(let i=1;i<=5;i++)add(`${String(offsets[i]).padStart(10,'0')} 00000 n \n`);add(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`);
    const url=URL.createObjectURL(new Blob(chunks,{type:'application/pdf'})),a=document.createElement('a');a.href=url;a.download=(title.replace(/[\\/:*?"<>|]/g,'_')||'Доска')+'.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  window.BoardPDF={bounds,arrow,download,textLines};
})();

