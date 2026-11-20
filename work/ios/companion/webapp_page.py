# -*- coding: utf-8 -*-
"""iPhone Safari 版界面（无需安装、无需签名）。

伴侣程序 serve 时顺带在 --http-port 上把这套页面发给手机浏览器：
    http://<电脑局域网IP>:47655/
页面内部用 fetch 调 /api/cmd，把命令转给同一个 Player，
所以轨迹录制、分组、重放、预设路径、抖动参数全都能在 iPhone 上用。
"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="超级虚拟定位">
<title>超级虚拟定位 · 网页版</title>
<style>
:root{--bg:#0d1220;--card:#161d2e;--line:#232d44;--txt:#e8ecf4;--dim:#9aa6bd;--blue:#2f6bff;--cyan:#35e6ff;--green:#2ed47a;--red:#ff3b57}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg);color:var(--txt);font:15px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
body{padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
header{position:sticky;top:0;z-index:30;background:linear-gradient(180deg,#111a2b,#0d1220);border-bottom:1px solid var(--line);padding:12px 14px 10px}
h1{margin:0;font-size:18px;font-weight:700;letter-spacing:.5px}
.sub{color:var(--dim);font-size:12px;margin-top:2px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--red);margin-right:6px;vertical-align:1px}
.dot.ok{background:var(--green)}
.tabs{display:flex;gap:6px;padding:10px 12px 0}
.tabs button{flex:1;padding:10px 0;border:0;border-radius:10px 10px 0 0;background:#131a29;color:var(--dim);font-size:14px}
.tabs button.on{background:var(--card);color:#fff;font-weight:600}
main{padding:12px}
.panel{display:none}
.panel.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:12px}
.row{display:flex;gap:8px;align-items:center;margin:8px 0}
.row>label{flex:0 0 92px;color:var(--dim);font-size:13px}
input,select,textarea{flex:1;min-width:0;background:#0e1524;border:1px solid var(--line);color:var(--txt);border-radius:10px;padding:10px;font-size:15px}
textarea{font-family:ui-monospace,Menlo,monospace;font-size:13px;min-height:96px}
input[type=range]{padding:0}
button{background:#0e1524;border:1px solid var(--line);color:var(--txt);border-radius:10px;padding:10px 12px;font-size:14px}
button.primary{background:var(--blue);border-color:transparent;color:#fff;font-weight:600}
button.danger{background:#3a1220;border-color:#5c1a2c;color:#ff8ba0}
button.ghost{background:transparent}
.title{font-size:13px;color:var(--cyan);font-weight:700;letter-spacing:.4px;margin:2px 0 8px}
.hint{color:var(--dim);font-size:12px;line-height:1.5;margin:6px 0 0}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.btns button{flex:1;min-width:88px}
.stat{font-size:13px;color:var(--dim);margin-top:8px;word-break:break-all}
#map{position:relative;height:260px;border-radius:12px;overflow:hidden;background:#0a0f1a;touch-action:none}
#map img.tile{position:absolute;width:256px;height:256px;left:0;top:0;user-select:none;-webkit-user-drag:none}
#map .mk{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:2px solid #fff;background:var(--blue);z-index:6;pointer-events:none}
#map .mk.first{background:var(--green)}
#map .mk.last{background:#ff8a3d}
#map svg{position:absolute;left:0;top:0;pointer-events:none;z-index:4}
#map .hud{position:absolute;left:8px;bottom:8px;background:rgba(10,15,26,.78);color:#cfd8ea;font-size:11.5px;padding:4px 8px;border-radius:8px;z-index:7}
#map .zbar{position:absolute;right:8px;bottom:8px;background:rgba(10,15,26,.78);color:#cfd8ea;font-size:11.5px;padding:4px 8px;border-radius:8px;z-index:7}
#map .zbtn{position:absolute;right:8px;top:8px;z-index:8;display:flex;flex-direction:column;gap:6px}
#map .zbtn button{width:36px;height:36px;padding:0;font-size:18px;border-radius:10px;background:rgba(14,21,36,.86)}
canvas{width:100%;height:180px;background:#10151f;border-radius:12px;display:block}
.list{margin-top:4px}
.item{display:flex;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid #1c2436}
.item:last-child{border-bottom:0}
.item .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .meta{color:var(--dim);font-size:11.5px}
.item button{padding:7px 10px;font-size:13px}
.badge{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;background:#1d2740;color:var(--cyan);margin-left:6px}
footer{color:var(--dim);font-size:11.5px;text-align:center;padding:10px 12px 24px}
</style>
</head>
<body>
<header>
  <h1>超级虚拟定位 · 网页版</h1>
  <div class="sub"><span id="dot" class="dot"></span><span id="conn">正在连接电脑端…</span></div>
</header>

<div class="tabs">
  <button id="t0" class="on" onclick="tab(0)">手动</button>
  <button id="t1" onclick="tab(1)">轨迹</button>
  <button id="t2" onclick="tab(2)">预设路径</button>
</div>

<main>
  <!-- 手动 -->
  <section id="p0" class="panel on">
    <div class="card">
      <div class="title">直接设坐标</div>
      <div class="row"><label>纬度</label><input id="lat" inputmode="decimal" placeholder="36.667662"></div>
      <div class="row"><label>经度</label><input id="lon" inputmode="decimal" placeholder="117.027707"></div>
      <div class="btns">
        <button class="primary" onclick="setPos(false)">应用坐标</button>
        <button onclick="useHere()">用手机当前位置</button>
      </div>
      <p class="hint">「应用坐标」只改一次位置；连续移动请用轨迹或预设路径。手机定位拿到的坐标会填入上面两个框。</p>
    </div>

    <div class="card">
      <div class="title">抖动（权重偏于）</div>
      <div class="row"><label>半径 <span id="vR">20</span> m</label><input id="radius" type="range" min="0" max="500" value="20" oninput="vR.textContent=this.value"></div>
      <div class="row"><label>权重 <span id="vW">55</span>%</label><input id="weight" type="range" min="0" max="100" value="55" oninput="vW.textContent=this.value"></div>
      <div class="row"><label>方位角</label><input id="bearing" inputmode="decimal" placeholder="留空 = 随机"></div>
      <div class="btns"><button onclick="applyJitter()">应用抖动参数</button><button class="ghost" onclick="api('jitter',{radius:0,bias:0})">关掉抖动</button></div>
      <p class="hint">权重越高越偏向方位角方向、方向越窄；半径 0 = 完全不抖。抖动在播放轨迹/路径时逐帧叠加。</p>
    </div>

    <div class="card">
      <div class="title">手机端定位权限</div>
      <div class="btns"><button onclick="askGeo()">申请定位</button><button class="danger" onclick="api('stop').then(say)">停止播放</button></div>
      <div class="stat" id="geostat">未申请</div>
    </div>
  </section>

  <!-- 轨迹 -->
  <section id="p1" class="panel">
    <div class="card">
      <div class="title">录制（用手机真实定位当样本）</div>
      <div class="row"><label>分组</label><select id="group"></select></div>
      <div class="row"><label>名称</label><input id="tname" placeholder="轨迹 MM-dd HH:mm"></div>
      <div class="btns"><button id="recbtn" class="primary" onclick="toggleRec()">开始录制</button><button onclick="exportSel()">导出选中</button></div>
      <div class="stat" id="recstat">未录制</div>
    </div>

    <div class="card">
      <div class="title">轨迹库（本机 Safari 存储）</div>
      <div class="btns"><button onclick="newGroup()">新建分组</button><button onclick="importJson()">粘贴 JSON 导入</button></div>
      <div class="list" id="tracks"></div>
    </div>

    <div class="card">
      <div class="title">重放</div>
      <div class="row"><label>速度倍率</label><input id="speed" inputmode="decimal" value="1.0"></div>
      <div class="row"><label>循环</label><select id="loop"><option value="0">不循环</option><option value="1">循环</option></select></div>
      <canvas id="cv" width="720" height="360"></canvas>
      <div class="btns"><button class="primary" onclick="playTrack()">开始重放</button><button onclick="api('pause').then(say)">暂停</button><button onclick="api('resume').then(say)">继续</button><button class="danger" onclick="api('stop').then(say)">停止</button></div>
      <div class="stat" id="playstat">未播放</div>
    </div>
  </section>

  <!-- 预设路径 -->
  <section id="p2" class="panel">
    <div class="card">
      <div class="title">地图选点（点地图加点）</div>
      <div id="map">
        <div class="zbtn"><button onclick="zoomBy(1)">＋</button><button onclick="zoomBy(-1)">－</button></div>
        <div class="hud" id="hud">z16 · 0 个节点</div>
        <div class="zbar" id="zbar">z16</div>
      </div>
      <div class="btns"><button onclick="clearNodes()">清空节点</button><button onclick="undoNode()">撤销</button><button onclick="addHereNode()">当前位置加点</button><button onclick="recenter()">回到 1 号</button></div>
      <p class="hint">点地图加节点（自动去重，3 米内重复点会忽略）；点节点上的数字可以删除。地图为高德瓦片，坐标已自动在 WGS-84 与 GCJ-02 之间换算。</p>
    </div>

    <div class="card">
      <div class="title">节点与每段速度</div>
      <div class="list" id="nodes"></div>
      <div class="row"><label>全局速度</label><input id="gv" inputmode="decimal" value="1.4"><span class="meta">m/s</span></div>
      <div class="row"><label>速度偏移</label><input id="goff" type="range" min="0" max="100" value="20" oninput="vO.textContent=this.value"><span class="meta"><span id="vO">20</span>%</span></div>
      <div class="row"><label>循环</label><select id="gloop"><option value="0">不循环</option><option value="1">循环</option></select></div>
      <div class="btns"><button class="primary" onclick="playRoute()">沿路径开始</button><button onclick="api('pause').then(say)">暂停</button><button class="danger" onclick="api('stop').then(say)">停止</button></div>
      <div class="stat" id="routestat">未播放</div>
      <p class="hint">每段实际速度 = 该段速度（留空则用全局速度）× (1 ± 偏移/100)，每 2.5 秒重采一次，限幅 0.2~25 m/s。</p>
    </div>
  </section>

  <footer>超级虚拟定位 · 网页版（无需安装） · 写给程序写在电脑端，页面只发命令</footer>
</main>

<script>
var API='/api/cmd';
var state={lat:36.667662,lon:117.027707,online:false,tracks:[],groups:[],sel:-1,nodes:[],recording:false,recPts:[],mapWgs:null};
var GRP_KEY='stv_groups',TRK_KEY='stv_tracks';

function $(id){return document.getElementById(id)}
function say(t){ if(typeof t!=='string') t=JSON.stringify(t); $('playstat').textContent=t }
function tab(i){for(var k=0;k<3;k++){$('t'+k).className=(k===i?'on':'');$('p'+k).className=(k===i?'panel on':'panel')}}

function api(cmd,extra){
  var body=Object.assign({cmd:cmd},extra||{});
  return fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json()}).catch(function(e){return {ok:false,error:String(e)}});
}

function poll(){
  api('status').then(function(r){
    state.online=!!r.ok;
    $('dot').className='dot'+(state.online?' ok':'');
    $('conn').textContent=state.online?('已连接电脑端 '+(location.host||'')):('未连接：'+(r.error||'检查电脑端是否在跑'));
    if(r.ok){
      if(r.running){
        var t='重放中 '+(r.progress||0).toFixed(1)+'% · '+Math.round(r.pushes||0)+' 帧 · v='+(r.speed||0).toFixed(2)+'m/s';
        if(r.segment!==undefined&&r.segment!==null)t+=' · 第'+r.segment+'段';
        if(r.jitter)t+=' · 抖动 '+r.jitter;
        if(r.manualPaused)t+=' · （已交回手动控制）';
        $('playstat').textContent=t;
        $('routestat').textContent=t;
      }
    }
  });
}

/* ---------- 坐标换算 ---------- */
var GCJ_A=6378245.0,GCJ_EE=0.00669342162296594323;
function outOfChina(lat,lng){return !(lng>73.66&&lng<135.05&&lat>3.86&&lat<53.55)}
function tLat(x,y){var r=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*Math.sqrt(Math.abs(x));
 r+=(20*Math.sin(6*x*Math.PI)+20*Math.sin(2*x*Math.PI))*2/3;
 r+=(20*Math.sin(y*Math.PI)+40*Math.sin(y/3*Math.PI))*2/3;
 r+=(160*Math.sin(y/12*Math.PI)+320*Math.sin(y*Math.PI/30))*2/3;return r}
function tLng(x,y){var r=300+x+2*y+0.1*x*x+0.1*x*y+0.1*Math.sqrt(Math.abs(x));
 r+=(20*Math.sin(6*x*Math.PI)+20*Math.sin(2*x*Math.PI))*2/3;
 r+=(20*Math.sin(x*Math.PI)+40*Math.sin(x/3*Math.PI))*2/3;
 r+=(150*Math.sin(x/12*Math.PI)+300*Math.sin(x/30*Math.PI))*2/3;return r}
function wgs2gcj(lat,lng){
  if(outOfChina(lat,lng))return[lat,lng];
  var dLat=tLat(lng-105,lat-35),dLng=tLng(lng-105,lat-35);
  var rl=lat/180*Math.PI,m=Math.sin(rl);m=1-GCJ_EE*m*m;var sm=Math.sqrt(m);
  dLat=(dLat*180)/((GCJ_A*(1-GCJ_EE))/(m*sm)*Math.PI);
  dLng=(dLng*180)/(GCJ_A/sm*Math.cos(rl)*Math.PI);
  return [lat+dLat,lng+dLng];
}
function gcj2wgs(lat,lng){
  if(outOfChina(lat,lng))return[lat,lng];
  var g=wgs2gcj(lat,lng);return [lat*2-g[0],lng*2-g[1]];
}

/* ---------- 地图 ---------- */
var map={c:{x:0,y:0},z:16,el:null,ready:false,img:[]};
function proj(lat,lng,z){var s=256*Math.pow(2,z);var x=(lng+180)/360*s;
 var r=lat*Math.PI/180;var y=(1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*s;return{x:x,y:y}}
function unproj(x,y,z){var s=256*Math.pow(2,z);var lng=x/s*360-180;
 var n=Math.PI-2*Math.PI*y/s;return{lat:180/Math.PI*Math.atan(0.5*(Math.exp(n)-Math.exp(-n))),lng:lng}}
function tileUrl(x,y,z){var s=['1','2','3','4'][(x+y)%4];
 return 'https://webrd0'+s+'.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x='+x+'&y='+y+'&z='+z}
function centerGcj(){ if(!map.ready)return null; return unproj(map.c.x,map.c.y,map.z) }
function setCenterGcj(lat,lng,z){ if(z)map.z=Math.max(4,Math.min(19,z)); var p=proj(lat,lng,map.z); map.c={x:p.x,y:p.y}; render() }
function zoomBy(d,ax,ay){
  var old=map.z, nz=Math.max(4,Math.min(19,old+d)); if(nz===old)return;
  var W=map.el.clientWidth,H=map.el.clientHeight;
  var sx=(ax===undefined?W/2:ax)-map.c.x, sy=(ay===undefined?H/2:ay)-map.c.y;
  var g=unproj(map.c.x+sx,map.c.y+sy,old);
  map.z=nz; var p=proj(g.lat,g.lng,nz);
  map.c={x:p.x-sx,y:p.y-sy}; render();
}
function render(){
  var el=map.el; if(!el)return; var W=el.clientWidth,H=el.clientHeight,T=256,Z=map.z;
  var x0=Math.floor((map.c.x-W/2)/T),x1=Math.floor((map.c.x+W/2)/T);
  var y0=Math.floor((map.c.y-H/2)/T),y1=Math.floor((map.c.y+H/2)/T);
  var need=[],i,j;
  for(i=x0;i<=x1;i++)for(j=y0;j<=y1;j++)need.push([i,j]);
  var used={};
  need.forEach(function(p){
    var key=p[0]+'_'+p[1],n=Math.pow(2,Z);
    var tx=((p[0]%n)+n)%n, ty=p[1]; if(ty<0||ty>=n)return;
    used[key]=1;
    var img=el.querySelector('img.tile[data-k="'+key+'"]');
    if(!img){
      img=document.createElement('img'); img.className='tile'; img.dataset.k=key;
      img.src=tileUrl(tx,ty,Z); img.style.zIndex=1; el.appendChild(img);
    }
    img.style.transform='translate('+Math.round(p[0]*T-map.c.x+W/2)+'px,'+Math.round(p[1]*T-map.c.y+H/2)+'px)';
  });
  Array.prototype.forEach.call(el.querySelectorAll('img.tile'),function(im){ if(!used[im.dataset.k]) im.remove() });
  // 折线与节点
  var svg=el.querySelector('#svg'); if(svg)svg.remove();
  svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.id='svg';
  svg.setAttribute('width',W); svg.setAttribute('height',H); el.appendChild(svg);
  var pts=state.nodes.map(function(n){var g=wgs2gcj(n.lat,n.lng),p=proj(g[0],g[1],Z);
    return {x:p.x-map.c.x+W/2,y:p.y-map.c.y+H/2}});
  if(pts.length>1){var d=pts.map(function(p){return p.x+','+p.y}).join(' ');
    var pl=document.createElementNS('http://www.w3.org/2000/svg','polyline');
    pl.setAttribute('points',d); pl.setAttribute('fill','none');
    pl.setAttribute('stroke','rgba(78,161,255,.85)'); pl.setAttribute('stroke-width','3'); svg.appendChild(pl)}
  Array.prototype.forEach.call(el.querySelectorAll('.mk'),function(m){m.remove()});
  pts.forEach(function(p,idx){
    var d=document.createElement('div'); d.className='mk'+(idx===0?' first':'')+(idx===pts.length-1&&idx>0?' last':'');
    d.style.transform='translate('+p.x+'px,'+p.y+'px)'; d.dataset.i=idx; el.appendChild(d);
  });
  $('hud').textContent='z'+Z+' · '+state.nodes.length+' 个节点';
  $('zbar').textContent='z'+Z;
}

var drag={on:false,x:0,y:0,moved:0};
function bindMap(){
  map.el=$('map');
  var here=state.nodes.length>0?state.nodes[0]:null;
  map.z=16; map.ready=true;
  if(here){var g=wgs2gcj(here.lat,here.lng);setCenterGcj(g[0],g[1],16)}
  else {var g2=wgs2gcj(state.lat,state.lon);setCenterGcj(g2[0],g2[1],16)}
  map.el.addEventListener('pointerdown',function(e){drag.on=true;drag.x=e.clientX;drag.y=e.clientY;drag.moved=0;map.el.setPointerCapture(e.pointerId)});
  map.el.addEventListener('pointermove',function(e){
    if(!drag.on)return;var dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    map.c.x-=dx;map.c.y-=dy;drag.x=e.clientX;drag.y=e.clientY;drag.moved+=Math.abs(dx)+Math.abs(dy);render();
  });
  map.el.addEventListener('pointerup',function(e){
    drag.on=false;
    var r=map.el.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top;
    if(drag.moved<14){
      var t=map.el.querySelector('.mk[data-i]');
      var hit=null;
      Array.prototype.forEach.call(map.el.querySelectorAll('.mk'),function(m){
        var tr=m.style.transform.match(/-?[\d.]+/g); if(!tr)return;
        var mx=parseFloat(tr[0]),my=parseFloat(tr[1]);
        if(Math.hypot(mx-px,my-py)<20)hit=parseInt(m.dataset.i,10);
      });
      if(hit!==null){state.nodes.splice(hit,1);renderNodes();render();return}
      var g=unproj(map.c.x+(px-map.el.clientWidth/2),map.c.y+(py-map.el.clientHeight/2),map.z);
      var w=gcj2wgs(g.lat,g.lng);
      addNode(w[0],w[1]);
    }
  });
  map.el.addEventListener('dblclick',function(e){zoomBy(1)});
  render();
}
function addNode(lat,lng,speed){
  for(var i=0;i<state.nodes.length;i++){
    if(Math.abs(state.nodes[i].lat-lat)<2.7e-5&&Math.abs(state.nodes[i].lng-lng)<2.7e-5){
      $('hud').textContent='已存在同位置节点，忽略';setTimeout(function(){render()},900);return;
    }
  }
  state.nodes.push({lat:lat,lng:lng,speed:speed||0}); renderNodes(); render();
}
function renderNodes(){
  var box=$('nodes');box.innerHTML='';
  if(!state.nodes.length){box.innerHTML='<div class="hint">还没有节点：在上面地图里点几下。</div>';return}
  state.nodes.forEach(function(n,i){
    var row=document.createElement('div');row.className='item';
    row.innerHTML='<div class="nm">'+(i+1)+'. '+n.lat.toFixed(6)+', '+n.lng.toFixed(6)+'</div>'+
      '<input style="flex:0 0 78px" inputmode="decimal" placeholder="全局" value="'+(n.speedMps||n.speed||'')+'">'+
      '<button class="danger">×</button>';
    var inp=row.querySelector('input');
    inp.addEventListener('input',function(){state.nodes[i].speed=parseFloat(inp.value)||0});
    row.querySelector('button').addEventListener('click',function(){state.nodes.splice(i,1);renderNodes();render()});
    box.appendChild(row);
  });
  drawCanvas();
}
function clearNodes(){state.nodes=[];renderNodes();render()}
function undoNode(){state.nodes.pop();renderNodes();render()}
function addHereNode(){askGeo(function(lat,lng){addNode(lat,lng);setCenterGcj(wgs2gcj(lat,lng)[0],wgs2gcj(lat,lng)[1],17)})}
function recenter(){if(!state.nodes.length)return;var g=wgs2gcj(state.nodes[0].lat,state.nodes[0].lng);setCenterGcj(g[0],g[1],16)}

/* ---------- 定位 ---------- */
var watchId=null,lastGeo=null;
function askGeo(cb){
  if(!navigator.geolocation){$('geostat').textContent='这个浏览器不支持定位';return}
  navigator.geolocation.getCurrentPosition(function(p){
    lastGeo={lat:p.coords.latitude,lng:p.coords.longitude,acc:p.coords.accuracy};
    $('geostat').textContent='定位：'+lastGeo.lat.toFixed(6)+', '+lastGeo.lng.toFixed(6)+'（精度 '+Math.round(lastGeo.acc||0)+' m）';
    if(cb)cb(lastGeo.lat,lastGeo.lng);
  },function(e){$('geostat').textContent='定位失败：'+e.message}, {enableHighAccuracy:true,timeout:12000,maximumAge:3000});
}
function useHere(){askGeo(function(lat,lng){$('lat').value=lat.toFixed(6);$('lon').value=lng.toFixed(6);setPos(true)})}

/* ---------- 命令 ---------- */
function setPos(quiet){
  var lat=parseFloat($('lat').value||state.lat),lon=parseFloat($('lon').value||state.lon);
  state.lat=lat;state.lon=lon;
  api('set',{lat:lat,lon:lon}).then(function(r){
    if(!quiet)say(r.ok?('已设置 '+lat.toFixed(6)+', '+lon.toFixed(6)):('失败：'+r.error));
  });
}
function applyJitter(){
  var b=$('bearing').value.trim();
  api('jitter',{radius:parseFloat($('radius').value),bias:parseInt($('weight').value,10)/100,
    bearing:b===''?null:parseFloat(b)}).then(function(r){
      say(r.ok?('抖动：'+(r.desc||'已应用')):('失败：'+r.error));
    });
}

/* ---------- 轨迹库 ---------- */
function loadLocal(){ try{state.groups=JSON.parse(localStorage.getItem(GRP_KEY)||'["默认分组"]');state.tracks=JSON.parse(localStorage.getItem(TRK_KEY)||'[]')}catch(e){state.groups=['默认分组'];state.tracks=[]} }
function saveLocal(){ localStorage.setItem(GRP_KEY,JSON.stringify(state.groups));localStorage.setItem(TRK_KEY,JSON.stringify(state.tracks)); }
function refreshGroups(){
  var sel=$('group');sel.innerHTML='';
  state.groups.forEach(function(g,i){var o=document.createElement('option');o.value=i;o.textContent=g;sel.appendChild(o)});
}
function newGroup(){var n=prompt('新分组名');if(!n)return;state.groups.push(n);saveLocal();refreshGroups();renderTracks()}
function renderTracks(){
  var box=$('tracks');box.innerHTML='';
  if(!state.tracks.length){box.innerHTML='<div class="hint">还没有轨迹。上面录一段，或粘贴 JSON 导入。</div>';return}
  state.tracks.forEach(function(t,i){
    var row=document.createElement('div');row.className='item';
    var m=t.points?t.points.length:0;
    row.innerHTML='<div class="nm">'+(t.name||('轨迹'+i))+'<span class="badge">'+m+' 点</span>'+
      '<div class="meta">'+(t.group||'默认分组')+' · '+(t.createdAt?new Date(t.createdAt).toLocaleString():'')+'</div></div>'+
      '<button>选</button><button class="danger">删</button>';
    row.querySelectorAll('button')[0].addEventListener('click',function(){state.sel=i;drawCanvas();say('已选：'+(t.name||('轨迹'+i)))});
    row.querySelectorAll('button')[1].addEventListener('click',function(){state.tracks.splice(i,1);saveLocal();renderTracks()});
    box.appendChild(row);
  });
}
function toggleRec(){
  if(watchId===null){
    if(!navigator.geolocation){$('recstat').textContent='不支持定位';return}
    state.recPts=[];
    watchId=navigator.geolocation.watchPosition(function(p){
      var t={t:Date.now(),lat:p.coords.latitude,lng:p.coords.longitude};
      var prev=state.recPts[state.recPts.length-1];
      if(prev&&Math.hypot(prev.lat-t.lat,prev.lng-t.lng)<8e-6)return;
      state.recPts.push(t);
      $('recstat').textContent='录制中：'+state.recPts.length+' 点（走一走再停）';
    },function(e){$('recstat').textContent='录制失败：'+e.message},{enableHighAccuracy:true,maximumAge:2000,timeout:15000});
    $('recbtn').textContent='停止并保存';$('recbtn').className='primary danger';
  }else{
    navigator.geolocation.clearWatch(watchId);watchId=null;
    $('recbtn').textContent='开始录制';$('recbtn').className='primary';
    if(state.recPts.length<2){$('recstat').textContent='少于 2 点，没保存';return}
    var gi=parseInt($('group').value,10)||0;
    state.tracks.push({name:$('tname').value||('轨迹 '+new Date().toLocaleString()),group:state.groups[gi]||'默认分组',
      createdAt:Date.now(),intervalMs:500,points:state.recPts});
    saveLocal();renderTracks();
    $('recstat').textContent='已保存 '+state.recPts.length+' 点';
  }
}
function importJson(){
  var raw=prompt('粘贴轨迹 JSON（{"name":..,"points":[[t,lat,lng],..]} 或 [[lat,lng],..]）');
  if(!raw)return;
  var data;try{data=JSON.parse(raw)}catch(e){alert('JSON 解析失败');return}
  var pts=Array.isArray(data)?data:(data.points||[]);
  var out=pts.map(function(p,i){
    if(Array.isArray(p)&&p.length>=3)return {t:p[0],lat:p[1],lng:p[2]};
    if(Array.isArray(p))return {t:i*500,lat:p[0],lng:p[1]};
    return {t:p.t||i*500,lat:p.lat,lng:p.lng};
  });
  var gi=parseInt($('group').value,10)||0;
  state.tracks.push({name:(data.name||'导入轨迹'),group:state.groups[gi]||'默认分组',createdAt:Date.now(),intervalMs:500,points:out});
  saveLocal();renderTracks();
}
function exportSel(){
  if(state.sel<0){say('先点「选」挑一条轨迹');return}
  var t=state.tracks[state.sel];
  var txt=JSON.stringify({name:t.name,intervalMs:t.intervalMs||500,points:t.points.map(function(p){return [p.t,p.lat,p.lng]})});
  navigator.clipboard&&navigator.clipboard.writeText(txt);
  try{var a=document.createElement('a');a.href='data:application/json;charset=utf-8,'+encodeURIComponent(txt);
    a.download=(t.name||'track')+'.json';a.click()}catch(e){}
  say('已导出 '+(t.points.length)+' 点（也复制到剪贴板）');
}
function playTrack(){
  if(state.sel<0){say('先点「选」挑一条轨迹');return}
  var t=state.tracks[state.sel];var b=$('bearing').value.trim();
  var payload={kind:'track',name:t.name,intervalMs:t.intervalMs||500,
    points:t.points.map(function(p){return [p.t,p.lat,p.lng]}),
    speed:parseFloat($('speed').value)||1.0,loop:$('loop').value==='1',
    radius:parseFloat($('radius').value)||0,bias:parseInt($('weight').value,10)/100,
    bearing:b===''?null:parseFloat(b)};
  api('play',{payload:payload}).then(function(r){say(r.ok?'开始重放：'+(t.name||''):('失败：'+r.error))});
}

/* ---------- 预设路径 ---------- */
function playRoute(){
  if(state.nodes.length<2){$('routestat').textContent='至少 2 个节点';return}
  var b=$('bearing').value.trim();
  var payload={kind:'route',name:'网页路径',globalSpeed:parseFloat($('gv').value)||1.4,
    offsetPercent:parseFloat($('goff').value)||0,loop:$('gloop').value==='1',
    radius:parseFloat($('radius').value)||0,bias:parseInt($('weight').value,10)/100,
    bearing:b===''?null:parseFloat(b),
    nodes:state.nodes.map(function(n){return [n.lat,n.lng,parseFloat(n.speedMps||n.speed)||0]})};
  api('play',{payload:payload}).then(function(r){$('routestat').textContent=r.ok?'沿路径开始':('失败：'+r.error)});
}

/* ---------- 预览画布 ---------- */
function drawCanvas(){
  var cv=$('cv'),ctx=cv.getContext('2d'),W=cv.width,H=cv.height;
  ctx.clearRect(0,0,W,H);ctx.fillStyle='#10151f';ctx.fillRect(0,0,W,H);
  var t=state.sel>=0?state.tracks[state.sel]:null;
  var pts=t?t.points:[];
  if(!pts.length&&state.nodes.length){pts=state.nodes.map(function(n,i){return {t:i*1000,lat:n.lat,lng:n.lng}})}
  if(!pts.length){ctx.fillStyle='#3d4761';ctx.font='16px sans-serif';ctx.fillText('选一条轨迹或在地图上加点，这里显示形状',18,H/2);return}
  var kx=111320*Math.cos(pts[0].lat*Math.PI/180),ky=110574;
  var xs=pts.map(function(p){return (p.lng-pts[0].lng)*kx}),ys=pts.map(function(p){return (p.lat-pts[0].lat)*ky});
  var minx=Math.min.apply(null,xs),maxx=Math.max.apply(null,xs),miny=Math.min.apply(null,ys),maxy=Math.max.apply(null,ys);
  var sx=maxx-minx||1,sy=maxy-miny||1,pad=24;
  var sc=Math.min((W-2*pad)/sx,(H-2*pad)/sy); if(!isFinite(sc)||sc<=0)sc=1;
  function X(i){return pad+(xs[i]-minx)*sc}
  function Y(i){return H-pad-(ys[i]-miny)*sc}
  ctx.strokeStyle='rgba(78,161,255,.9)';ctx.lineWidth=3;ctx.beginPath();
  for(var i=0;i<pts.length;i++){ i?ctx.lineTo(X(i),Y(i)):ctx.moveTo(X(i),Y(i)) } ctx.stroke();
  ctx.fillStyle='#2ed47a';ctx.beginPath();ctx.arc(X(0),Y(0),5,0,7);ctx.fill();
  ctx.fillStyle='#ff8a3d';ctx.beginPath();ctx.arc(X(pts.length-1),Y(pts.length-1),5,0,7);ctx.fill();
  ctx.fillStyle='#9aa6bd';ctx.font='12px sans-serif';
  ctx.fillText(pts.length+' 点',12,18);
}

/* ---------- 启动 ---------- */
loadLocal();refreshGroups();renderTracks();
api('status').then(function(){setPos(true)});
setTimeout(function(){bindMap();drawCanvas()},60);
setInterval(poll,700);poll();
window.addEventListener('resize',function(){render();drawCanvas()});
</script>
</body>
</html>
"""