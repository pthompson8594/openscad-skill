#!/usr/bin/env python3
"""mark3d.py model.stl [mark.stl] out.html
Self-contained interactive viewer. No mark: solid model, orbit/zoom/pan + ghost
toggle. With mark: model translucent gray, mark solid red, focus-mark button.
Binary STLs embedded base64; three.js via cdnjs; hand-rolled controls.
"""
import base64, struct, sys

def info(p):
    d = open(p, 'rb').read()
    n = struct.unpack('<I', d[80:84])[0]
    lo = [1e30]*3; hi = [-1e30]*3
    for i in range(n):
        t = struct.unpack('<9f', d[84+i*50+12:84+i*50+48])
        for j in range(9):
            a = j % 3
            if t[j] < lo[a]: lo[a] = t[j]
            if t[j] > hi[a]: hi[a] = t[j]
    mid = [(lo[k]+hi[k])/2 for k in range(3)]
    dia = sum((hi[k]-lo[k])**2 for k in range(3))**0.5
    return base64.b64encode(d).decode(), mid, max(dia, 1)

model = sys.argv[1]; mark = sys.argv[2] if len(sys.argv) == 4 else None
out = sys.argv[-1]
mb64, mmid, mdia = info(model)
kb64, kmid, kdia = info(mark) if mark else ("", mmid, mdia)

html = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0;background:#222;overflow:hidden;font-family:sans-serif;touch-action:none}
#hud{position:fixed;top:10px;left:10px;color:#ddd;font-size:13px}
button{background:#444;color:#eee;border:1px solid #666;border-radius:4px;padding:4px 10px;margin-right:6px;cursor:pointer}
button:hover{background:#555}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head><body><div id="hud">
<button onclick="focusAll()">whole part</button>__MARKBTN__
<button onclick="ghost=!ghost;mat.opacity=ghost?0.28:0.95;mat.transparent=ghost;mat.depthWrite=!ghost">toggle ghost</button>
__LEGEND__ drag: orbit &nbsp; wheel or pinch: zoom &nbsp; right-drag or two fingers: pan</div>
<script>
const MODEL="__MB64__", MARK="__KB64__";
const MMID=[__MMID__], KMID=[__KMID__], MDIA=__MDIA__, KDIA=__KDIA__;
function stl(b64){const s=atob(b64),u=new Uint8Array(s.length);
 for(let i=0;i<s.length;i++)u[i]=s.charCodeAt(i);
 const dv=new DataView(u.buffer),n=dv.getUint32(80,true),p=new Float32Array(n*9);let o=84;
 for(let i=0;i<n;i++){o+=12;for(let j=0;j<9;j++){p[i*9+j]=dv.getFloat32(o,true);o+=4;}o+=2;}
 const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(p,3));
 g.computeVertexNormals();return g;}
const scene=new THREE.Scene();scene.background=new THREE.Color(0x222222);
const root=new THREE.Group();root.rotation.x=-Math.PI/2;scene.add(root); // z-up
let ghost=__GHOST__;
const mat=new THREE.MeshPhongMaterial({color:0xb9c4cf,transparent:ghost,opacity:ghost?0.28:0.95,side:THREE.DoubleSide,depthWrite:!ghost});
root.add(new THREE.Mesh(stl(MODEL),mat));
if(MARK)root.add(new THREE.Mesh(stl(MARK),new THREE.MeshPhongMaterial({color:0xdd2222,side:THREE.DoubleSide})));
scene.add(new THREE.HemisphereLight(0xffffff,0x445566,0.9));
const dl=new THREE.DirectionalLight(0xffffff,0.7);dl.position.set(1,2,1.5);scene.add(dl);
const cam=new THREE.PerspectiveCamera(45,innerWidth/innerHeight,0.1,MDIA*50);
const ren=new THREE.WebGLRenderer({antialias:true});ren.setSize(innerWidth,innerHeight);document.body.appendChild(ren.domElement);
const w=v=>new THREE.Vector3(v[0],v[2],-v[1]);
let tgt=w(MMID),rad=MDIA*1.1,th=0.9,ph=1.05;
function focusAll(){tgt=w(MMID);rad=MDIA*1.1;}
function focusMark(){tgt=w(KMID);rad=Math.max(KDIA*3.5,MDIA*0.12);}
let drag=0,pd=0,pmx=0,pmy=0;const P=new Map();
function pan(dx,dy){const s=rad*0.0015,r=new THREE.Vector3().crossVectors(cam.up,dirv()).normalize();tgt.addScaledVector(r,dx*s);tgt.y+=dy*s;}
addEventListener('pointerdown',e=>{if(e.target.tagName==='BUTTON')return;P.set(e.pointerId,[e.clientX,e.clientY]);drag=e.button===2?2:1;});
addEventListener('pointerup',e=>{P.delete(e.pointerId);pd=0;if(!P.size)drag=0;});
addEventListener('pointercancel',e=>{P.delete(e.pointerId);pd=0;});
addEventListener('contextmenu',e=>e.preventDefault());
addEventListener('pointermove',e=>{const q=P.get(e.pointerId);if(!q)return;const dx=e.clientX-q[0],dy=e.clientY-q[1];q[0]=e.clientX;q[1]=e.clientY;
 if(P.size===2){const a=[...P.values()],d=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]),mx=(a[0][0]+a[1][0])/2,my=(a[0][1]+a[1][1])/2;
  if(pd){rad=Math.max(MDIA*0.02,Math.min(MDIA*8,rad*pd/d));pan(mx-pmx,my-pmy);}pd=d;pmx=mx;pmy=my;return;}
 if(drag===1){th+=dx*0.008;ph=Math.min(3.0,Math.max(0.15,ph-dy*0.008));}else if(drag===2)pan(dx,dy);});
addEventListener('wheel',e=>{rad*=e.deltaY>0?1.12:0.89;rad=Math.max(MDIA*0.02,Math.min(MDIA*8,rad));});
addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();ren.setSize(innerWidth,innerHeight);});
function dirv(){return new THREE.Vector3(Math.sin(ph)*Math.cos(th),Math.cos(ph),Math.sin(ph)*Math.sin(th));}
(function loop(){requestAnimationFrame(loop);
 cam.position.copy(tgt).addScaledVector(dirv(),rad);cam.lookAt(tgt);ren.render(scene,cam);})();
</script></body></html>
"""
html = (html.replace("__MB64__", mb64).replace("__KB64__", kb64)
            .replace("__MMID__", ",".join("%.3f" % v for v in mmid))
            .replace("__KMID__", ",".join("%.3f" % v for v in kmid))
            .replace("__MDIA__", "%.2f" % mdia).replace("__KDIA__", "%.2f" % kdia)
            .replace("__GHOST__", "true" if mark else "false")
            .replace("__MARKBTN__", '<button onclick="focusMark()">focus mark</button>' if mark else "")
            .replace("__LEGEND__", '<span style="color:#e33">&#9632;</span> mark &nbsp;' if mark else ""))
open(out, 'w').write(html)
print("viewer: %s (%d KB)" % (out, len(html)//1024))
