// Canvas scene with bounded geometry; no external assets or WebGL dependency.
export const defaultCamera = () => ({ yaw: -12, pitch: 24, zoom: 1, x: 0, y: 0 });
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export function moveCamera(camera, button, dx, dy) {
  if (button === 0) { camera.yaw -= dx * .4; camera.pitch += dy * .25; }
  if (button === 2) camera.zoom = clamp(camera.zoom * Math.exp(-dy * .009), .4, 3);
  if (button === 1) { camera.x += dx; camera.y += dy; }
}
export function layoutTasks(tasks) {
  const groups = [], positions = new Map();
  for (const task of [...tasks].sort((a,b) => a.group.localeCompare(b.group) || a.pid.localeCompare(b.pid))) {
    let group = groups.find(g => g.name === task.group);
    if (!group) { group = { name: task.group, tasks: [] }; groups.push(group); }
    group.tasks.push(task);
  }
  let x = 0, depth = 1;
  for (const group of groups) {
    group.cols = Math.min(12, group.tasks.length <= 32 ? Math.ceil(group.tasks.length / 8) : Math.ceil(Math.sqrt(group.tasks.length * .8)));
    group.rows = Math.ceil(group.tasks.length / group.cols);
    group.x = x;
    group.tasks.forEach((task, i) => positions.set(task.pid, { task, x: x + i % group.cols + .5, z: Math.floor(i / group.cols) + .5, row: Math.floor(i / group.cols)+1, col: i % group.cols+1 }));
    x += group.cols + 1.6;
    depth = Math.max(depth, group.rows);
  }
  return { groups, positions, width: Math.max(1, x - 1.6), depth };
}
export function minuteOf(time) {
  const value = String(time || '').match(/[T ](\d{2}):(\d{2}):(\d{2})/);
  return value ? Number(value[1])*60 + Number(value[2]) + Number(value[3])/60 : 0;
}

export function createPerspectiveProjection(bounds, camera, width, height) {
  const center=bounds.min.map((v,i)=>(v+bounds.max[i])/2);
  const radius=Math.max(.1,Math.hypot(...bounds.max.map((v,i)=>(v-bounds.min[i])/2)));
  const a=(camera.yaw%360)*Math.PI/180,b=(camera.pitch%360)*Math.PI/180;
  const ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b);
  const rotate=(x,y,z)=>{x-=center[0];y-=center[1];z-=center[2];const rx=x*ca-z*sa,rz=x*sa+z*ca;return [rx,rz*sb-y*cb,rz*cb+y*sb];};
  // Fixed 45 degree vertical field of view, with room for a full orbit at any angle.
  const availableW=Math.max(1,width-100),availableH=Math.max(1,height-75),halfFov=Math.PI/8;
  const focal=availableH/(2*Math.tan(halfFov));
  const distance=radius/Math.sin(Math.min(halfFov,Math.atan(availableW/(2*focal))))*1.1;
  const eye=[center[0]+distance*sa*cb,center[1]+distance*sb,center[2]+distance*ca*cb];
  return {
    project(x,y,z){const p=rotate(x,y,z),factor=focal*camera.zoom/(distance-p[2]);return [width/2+p[0]*factor+camera.x,height/2+p[1]*factor+camera.y];},
    depth(x,y,z){return rotate(x,y,z)[2];},
    facing(point,normal){return normal.reduce((sum,n,i)=>sum+n*(eye[i]-point[i]),0)>1e-8;},
  };
}

function shade(color, factor) {
  return '#'+[1,3,5].map(i=>Math.round(parseInt(color.slice(i,i+2),16)*factor).toString(16).padStart(2,'0')).join('');
}

function inside(p, vertices) {
  let result = false;
  for (let i=0,j=vertices.length-1; i<vertices.length; j=i++) {
    const a=vertices[i], b=vertices[j];
    if ((a[1]>p[1]) !== (b[1]>p[1]) && p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]) result=!result;
  }
  return result;
}

export function createMatrixScene(canvas, onSelect, options = {}) {
  const ctx = canvas.getContext('2d');
  const safeCamera = value => Object.fromEntries(Object.entries(defaultCamera()).map(([key, fallback]) => [key, Number.isFinite(value?.[key]) ? (key==='zoom' ? clamp(value[key],.4,3) : value[key]) : fallback]));
  let camera = safeCamera(options.camera), data = null, selected = '', selectedKey = '', focused = false, frame = 0, hits = [], drag = null, suppressMenu = false;
  let width=1, height=1;
  function schedule() { if (!frame) frame = requestAnimationFrame(draw); }
  function draw() {
    frame=0; hits=[];
    if (!data || !width || !ctx) return;
    const style=getComputedStyle(document.documentElement);
    const colors={ ink:style.getPropertyValue('--ink').trim() || '#d9e4ef', muted:style.getPropertyValue('--muted').trim() || '#91a4b7', line:style.getPropertyValue('--line').trim() || '#2a3a49', brand:style.getPropertyValue('--brand').trim() || '#2dd4bf', success:'#40cf88', failed:'#f16d78', running:'#f6cf54', pending:'#9cacbf', queued:'#bdc8d6', cancelled:'#91a1b7', timed_out:'#e45364',interrupted:'#ae8ad8',skipped:'#8897aa',missed:'#a397c1',unknown:'#a397c1' };
    const grid='#70849b';
    ctx.clearRect(0,0,width,height);
    const layout=layoutTasks(data.tasks), today=data.date===data.server_time.slice(0,10), current=today?minuteOf(data.server_time):1440;
    const unit=7.1/Math.max(60,current), currentY=current*unit;
    const pending=data.pending.filter(r => minuteOf(r.time)>=current && minuteOf(r.time)<=current+120);
    const marks=[...data.records,...data.active,...pending];
    const heightAt=r => r.status==='running'||r.status==='queued' ? currentY : minuteOf(r.time)*unit;
    const bounds={min:[-1.3,-.1,0],max:[layout.width,Math.max(currentY+.4,...pending.map(r=>heightAt(r)+.2)),layout.depth+1]};
    const projection=createPerspectiveProjection(bounds,camera,width,height),project=projection.project,depth=projection.depth;
    const poly=(vertices,fill,stroke,alpha=1,line=1) => { ctx.save(); ctx.globalAlpha=alpha; ctx.beginPath(); vertices.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=line;ctx.stroke();}ctx.restore(); };
    const plane=(p,y,half=.5) => [[p.x-half,y,p.z-half],[p.x+half,y,p.z-half],[p.x+half,y,p.z+half],[p.x-half,y,p.z+half]].map(v=>project(...v));
    const objects=[];
    layout.positions.forEach(p => {
      objects.push({depth:depth(p.x,0,p.z),paint(){poly(plane(p,0),grid,null,.15);poly(plane(p,0),null,grid,.65);hits.push({v:plane(p,0),value:{pid:p.task.pid}});}});
      objects.push({depth:depth(p.x,currentY,p.z),paint(){poly(plane(p,currentY),grid,null,.15);poly(plane(p,currentY),null,grid,.6); if(p.task.pid===selected) poly(plane(p,currentY),colors.brand,colors.brand,.32,2);hits.push({v:plane(p,currentY),value:{pid:p.task.pid}});}});
    });
    marks.forEach(r => {
      const p=layout.positions.get(r.pid); if(!p) return;
      const y=heightAt(r)+.045, color=colors[r.status]||colors.unknown, alpha=focused&&r.pid!==selected?.14:1;
      const top=plane(p,y,.39),bottom=plane(p,y-.065,.39),vertices=[...top,...bottom];
      const faces=r.status==='pending' ? [{v:top,center:[p.x,y,p.z],factor:1,marker:true}] : [
        {v:top,center:[p.x,y,p.z],normal:[0,1,0],factor:1,marker:true},
        {v:bottom,center:[p.x,y-.065,p.z],normal:[0,-1,0],factor:.8,marker:true},
        {v:[0,3,7,4].map(i=>vertices[i]),center:[p.x-.39,y-.0325,p.z],normal:[-1,0,0],factor:.65},
        {v:[1,2,6,5].map(i=>vertices[i]),center:[p.x+.39,y-.0325,p.z],normal:[1,0,0],factor:.82},
        {v:[0,1,5,4].map(i=>vertices[i]),center:[p.x,y-.0325,p.z-.39],normal:[0,0,-1],factor:.7},
        {v:[3,2,6,7].map(i=>vertices[i]),center:[p.x,y-.0325,p.z+.39],normal:[0,0,1],factor:.9},
      ];
      for(const face of faces) {
        if(face.normal&&!projection.facing(face.center,face.normal))continue;
        objects.push({depth:depth(...face.center),paint(){
          poly(face.v,r.status==='pending'?null:shade(color,face.factor),r.status==='pending'?color:colors.ink,alpha,r.status==='pending'?1.5:.4);
          if(r.pid===selected)poly(face.v,null,colors.ink,alpha,1.3);
          if(r.key===selectedKey)poly(face.v,null,colors.brand,1,2.5);
          if(face.marker&&(r.status==='failed'||r.status==='timed_out'||r.status==='running')) {
            const c=project(...face.center),tileWidth=Math.hypot(face.v[1][0]-face.v[0][0],face.v[1][1]-face.v[0][1]);
            ctx.save();ctx.globalAlpha=alpha;ctx.fillStyle=colors.ink;ctx.font=`bold ${Math.max(9,Math.min(15,tileWidth*.3))}px sans-serif`;ctx.textAlign='center';ctx.fillText(['failed','timed_out'].includes(r.status)?'×':'···',c[0],c[1]+3);ctx.restore();
          }
          if(alpha>.2)hits.push({v:face.v,value:r});
        }});
      }
    });
    objects.sort((a,b)=>a.depth-b.depth).forEach(o=>o.paint());
    const axisStart=project(-1,0,0),axisEnd=project(-1,currentY+.3,0);
    ctx.strokeStyle=colors.muted;ctx.lineWidth=1.4;ctx.beginPath();ctx.moveTo(...axisStart);ctx.lineTo(...axisEnd);ctx.stroke();
    ctx.font='12px sans-serif';ctx.textAlign='right';ctx.fillStyle=colors.muted;
    ctx.fillText('00:00',axisStart[0]-8,axisStart[1]+4);
    ctx.fillText(today?data.server_time.slice(11,16):'24:00',axisEnd[0]-8,axisEnd[1]);
    const labels=[];
    layout.groups.forEach(g => {
      const p=project(g.x+g.cols/2,0,g.rows+.55),text=`${g.name} · ${g.tasks.length}`,tw=ctx.measureText(text).width+18;
      let x=clamp(p[0],tw/2+5,width-tw/2-5),y=clamp(p[1],16,height-16);
      for(const old of labels) if(Math.abs(x-old.x)<(tw+old.tw)/2 && Math.abs(y-old.y)<21) y=clamp(old.y+23,16,height-12);
      labels.push({x,y,tw});ctx.save();ctx.globalAlpha=.95;ctx.fillStyle='#202d3d';ctx.fillRect(x-tw/2,y-13,tw,22);ctx.strokeStyle=colors.line;ctx.strokeRect(x-tw/2,y-13,tw,22);ctx.fillStyle=colors.ink;ctx.textAlign='center';ctx.fillText(text,x,y+2);ctx.restore();
    });
  }
  function down(e) {
    suppressMenu=e.altKey&&e.button===2;
    if(e.altKey){e.preventDefault();canvas.setPointerCapture(e.pointerId);}
    drag={id:e.pointerId,button:e.button,alt:e.altKey,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};
  }
  function move(e) {
    if(!drag||drag.id!==e.pointerId||!drag.alt) return;
    moveCamera(camera,drag.button,e.clientX-drag.x,e.clientY-drag.y);
    camera.x=clamp(camera.x,-width,width);camera.y=clamp(camera.y,-height,height);
    drag.x=e.clientX;drag.y=e.clientY;schedule();
  }
  function up(e) {
    if(!drag||drag.id!==e.pointerId) return;
    if(!drag.alt&&drag.button===0&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5) {
      const rect=canvas.getBoundingClientRect(),p=[e.clientX-rect.left,e.clientY-rect.top];
      // Reference planes are translucent; let visible execution pieces be selected through them.
      const candidates=[...hits].reverse().filter(h=>inside(p,h.v));
      const hit=candidates.find(h=>h.value.key)||candidates[0];if(hit) onSelect(hit.value);
    }
    options.onCamera?.({...camera});
    drag=null;
    if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
  }
  const menu=e=>{if(e.altKey||suppressMenu)e.preventDefault();};
  const cancel=()=>{drag=null;};
  canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('lostpointercapture',cancel);canvas.addEventListener('contextmenu',menu);
  const resize=new ResizeObserver(()=>{const rect=canvas.getBoundingClientRect();width=rect.width;height=rect.height;const dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx?.setTransform(dpr,0,0,dpr,0,0);schedule();});resize.observe(canvas);
  return {
    update(snapshot,pid,focus,key){data=snapshot;selected=pid;focused=focus;selectedKey=key;schedule();},
    getCamera(){return {...camera};},
    setCamera(value){camera=safeCamera(value);schedule();},
    restore(){camera=defaultCamera();options.onCamera?.({...camera});schedule();},
    keyboard(e){if(!e.altKey)return;const moves={ArrowRight:[0,25,0],ArrowLeft:[0,-25,0],ArrowUp:[0,0,-20],ArrowDown:[0,0,20],'+':[2,0,-20],'-':[2,0,20]};if(moves[e.key]){e.preventDefault();moveCamera(camera,...moves[e.key]);options.onCamera?.({...camera});schedule();}},
    dispose(){resize.disconnect();cancelAnimationFrame(frame);for(const [event,handler] of [['pointerdown',down],['pointermove',move],['pointerup',up],['pointercancel',cancel],['lostpointercapture',cancel],['contextmenu',menu]])canvas.removeEventListener(event,handler);}
  };
}
