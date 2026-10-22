"""Synthetic application forms for local read-only acceptance; never contacts a real employer.

Form posts are recorded so tests can prove the platform never submits anything."""
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

FORM = '''<!doctype html><html><head><meta charset="utf-8"><title>合成申请表</title></head><body>
<h1>合成岗位申请表 JOB-1</h1>
<form method="post" action="/submit" enctype="multipart/form-data">
<label for="name">姓名</label><input id="name" name="name">
<label for="email">邮箱</label><input id="email" name="email" type="email">
<label for="school">毕业院校</label><input id="school" name="school">
<label for="degree">最高学历</label><select id="degree" name="degree"><option value="">请选择</option><option value="bachelor">本科</option><option value="master">硕士</option></select>
<label for="start">入学时间</label><input id="start" name="start" type="month">
<label for="end">毕业时间</label><input id="end" name="end" type="month">
<label for="salary">期望薪资</label><input id="salary" name="salary">
<label for="intro">自我介绍</label><textarea id="intro" name="intro"></textarea>
<label for="resume">上传简历</label><input id="resume" name="resume" type="file">
<button type="submit">提交申请</button>
</form>
<script>/*SCRIPT*/</script>
</body></html>'''


def create_site():
    app = FastAPI()
    app.state.submissions = []

    @app.get('/apply', response_class=HTMLResponse)
    def form():
        return FORM.replace('/*SCRIPT*/', '')

    @app.post('/{path}', response_class=HTMLResponse)
    async def record(path: str, request: Request):
        # Any post at all is a failure for read-only features.
        app.state.submissions.append({'path': path, 'body': await request.body()})
        return '<!doctype html><html><body><h1>已提交</h1></body></html>'

    return app


class SiteServer:
    def __init__(self, app):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        self.app = app
        self.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=self.port, log_level='warning'))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.port}'

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError('synthetic site did not start')
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


COMPONENT_FORM = '''<!doctype html><html><head><meta charset="utf-8"><title>合成招聘系统</title><style>
body{font-family:sans-serif;margin:0;padding:20px 40px;width:900px} .el-form-item{display:flex;gap:12px;margin:10px 0;align-items:center}
.el-form-item__label{width:110px} .el-form-item.is-required .el-form-item__label::before{content:"*";color:red}
.el-select,.el-cascader,.el-date-editor{position:relative;width:300px} .el-select input,.el-cascader input,.el-date-editor input,.el-input input{width:280px;padding:6px}
.el-select-dropdown,.el-cascader-menus{position:absolute;z-index:2000;background:#fff;border:1px solid #ccc;display:none}
.el-cascader-menus{height:260px;width:420px} .el-cascader-menu{display:inline-block;vertical-align:top;width:200px}
li{list-style:none;padding:6px 10px;cursor:pointer} .el-upload-dragger{border:2px dashed #aaa;padding:20px;width:300px;cursor:pointer}
</style></head><body>
<h2>你正在投递职位：合成岗位 JOB-9</h2>
<form id="form" method="post" action="/submit2" enctype="multipart/form-data">
<h3>上传简历</h3>
<div class="el-form-item"><label class="el-form-item__label">简历附件</label>
 <div class="el-upload" id="upload"><div class="el-upload-dragger" onclick="document.getElementById('resume').click()">拖拽或点击上传简历，我们帮你快速解析~</div>
 <input type="file" name="resume" id="resume" style="display:none"></div></div>
<h3>个人信息</h3>
<div class="el-form-item is-required"><label class="el-form-item__label">姓名</label><div class="el-input"><input name="name" placeholder="请输入"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">邮箱</label><div class="el-input"><input name="email" placeholder="请输入"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">性别</label><div class="el-radio-group">
 <label class="el-radio"><input type="radio" name="gender" value="男"><span class="el-radio__label">男</span></label>
 <label class="el-radio"><input type="radio" name="gender" value="女"><span class="el-radio__label">女</span></label></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">政治面貌</label><div class="el-select" data-options="中共党员,共青团员,群众"><input name="politics" readonly placeholder="请选择"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">籍贯</label><div class="el-cascader"><input name="hometown" readonly placeholder="请选择"></div></div>
<h3>教育经历</h3>
<div class="el-form-item is-required"><label class="el-form-item__label">学校名称</label><div class="el-input"><input name="school" placeholder="请输入"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">学历</label><div class="el-select" data-options="本科,硕士研究生,博士研究生"><input name="degree" readonly placeholder="请选择"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">入学时间</label><div class="el-date-editor"><input name="start" placeholder="选择月份"></div></div>
<div class="el-form-item is-required"><label class="el-form-item__label">毕业时间</label><div class="el-date-editor"><input name="end" placeholder="选择月份"></div></div>
<div class="el-form-item"><label class="el-form-item__label">自我评价</label><div class="el-input"><textarea name="intro" placeholder="请输入"></textarea></div></div>
<button type="submit">预览并提交</button>
</form>
<script>
const regions={"山西省":["太原市","阳泉市"],"广东省":["深圳市","广州市"]};
function closeAll(){document.querySelectorAll('.el-select-dropdown,.el-cascader-menus').forEach(p=>p.style.display='none');}
function place(p,host){const r=host.getBoundingClientRect();p.style.left=(r.left+scrollX)+'px';p.style.top=(r.bottom+scrollY)+'px';p.style.display='block';}
document.querySelectorAll('.el-select').forEach(sel=>{
  const input=sel.querySelector('input');const pop=document.createElement('div');pop.className='el-select-dropdown';
  pop.innerHTML='<ul>'+sel.dataset.options.split(',').map(o=>'<li class="el-select-dropdown__item">'+o+'</li>').join('')+'</ul>';
  document.body.appendChild(pop);
  input.addEventListener('click',e=>{e.stopPropagation();closeAll();place(pop,sel);});
  pop.addEventListener('mousedown',e=>e.stopPropagation());
  pop.querySelectorAll('li').forEach(li=>li.addEventListener('click',e=>{e.stopPropagation();input.value=li.textContent;pop.style.display='none';}));
});
const cas=document.querySelector('.el-cascader'),casInput=cas.querySelector('input'),menus=document.createElement('div');
menus.className='el-cascader-menus';document.body.appendChild(menus);menus.addEventListener('mousedown',e=>e.stopPropagation());
function renderCas(province){
  menus.innerHTML='<ul class="el-cascader-menu">'+Object.keys(regions).map(p=>'<li class="el-cascader-node" data-p="'+p+'">'+p+'</li>').join('')+'</ul>'+
   (province?'<ul class="el-cascader-menu">'+regions[province].map(c=>'<li class="el-cascader-node" data-c="'+c+'">'+c+'</li>').join('')+'</ul>':'');
  menus.querySelectorAll('[data-p]').forEach(li=>li.addEventListener('click',e=>{e.stopPropagation();renderCas(li.dataset.p);}));
  // Like many real cascaders, choosing a city updates the input but leaves the panel open over the fields below.
  menus.querySelectorAll('[data-c]').forEach(li=>li.addEventListener('click',e=>{e.stopPropagation();casInput.value=province+' / '+li.dataset.c;}));
}
casInput.addEventListener('click',e=>{e.stopPropagation();closeAll();renderCas('');place(menus,cas);});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeAll();});
document.addEventListener('mousedown',()=>closeAll());
const resume=document.getElementById('resume');
resume.addEventListener('change',()=>{
  // Re-render the upload area (the original drop zone disappears) and auto-fill parsed fields.
  const up=document.getElementById('upload');const fresh=document.createElement('div');fresh.className='el-upload el-upload--done';
  fresh.id='upload';fresh.innerHTML='<div class="el-upload-list"><span class="file-name">'+resume.files[0].name+'</span> 解析完成</div>';
  fresh.appendChild(resume);up.replaceWith(fresh);
  setTimeout(()=>{const n=document.querySelector('[name=name]'),m=document.querySelector('[name=email]');n.value='张三';m.value='zhangsan@example.com';},300);
});
</script></body></html>'''


def add_component_form(app):
    @app.get('/apply2', response_class=HTMLResponse)
    def component_form():
        return COMPONENT_FORM

    return app


# Vendor-style form with no known component-library classes: names sit in sibling elements, the inner wrapper only holds
# a "请输入" input, dropdowns are plain divs showing "请选择" with option layers pre-rendered (hidden) at the end of <body>
# (two of them both contain "山西省"), the file input lives outside every form row, and the site's resume parser gets fields wrong.
VENDOR_FORM = '''<!doctype html><html><head><meta charset="utf-8"><title>合成网申系统</title><style>
body{font-family:sans-serif;margin:0;padding:20px 40px;width:900px} .vd-line{display:flex;gap:12px;margin:10px 0;align-items:center}
.vd-name{width:110px} .vd-name i{color:red;font-style:normal} .vd-dd{width:300px;border:1px solid #ccc;padding:6px;cursor:pointer}
.vd-layer{position:absolute;z-index:3000;background:#fff;border:1px solid #ccc;display:none;max-height:240px;overflow:auto}
.vd-col{display:inline-block;vertical-align:top;width:140px} .vd-opt{padding:6px 10px;cursor:pointer} input{width:280px;padding:6px}
.vd-cal td{padding:4px 8px;cursor:pointer}
</style></head><body>
<h2>合成网申 · 岗位 JOB-7</h2>
<div class="vd-attach"><span>附件简历</span><button type="button" onclick="document.getElementById('cv').click()">上传附件简历</button>
 <input type="file" id="cv" style="display:none"></div>
<form id="form" method="post" action="/submit3" enctype="multipart/form-data">
<h3>基本信息</h3>
<div class="vd-line"><div class="vd-name"><i>*</i>姓名</div><div class="vd-form-item__inner"><input name="name" placeholder="请输入"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>手机号码</div><div class="vd-form-item__inner"><input name="phone" placeholder="请输入"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>民族</div><div class="vd-form-item__inner"><div class="vd-dd" data-layer="nation"><span>请选择</span></div><input type="hidden" name="nation"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>户口所在地</div><div class="vd-form-item__inner"><div class="vd-dd" data-layer="huko"><span>请选择</span></div><input type="hidden" name="huko"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>籍贯</div><div class="vd-form-item__inner"><div class="vd-dd" data-layer="origin"><span>请选择</span></div><input type="hidden" name="origin"></div></div>
<div class="vd-line"><div class="vd-name">通讯地址</div><div class="vd-form-item__inner"><input name="address" placeholder="请输入"></div></div>
<h3>教育经历</h3>
<div class="vd-line"><div class="vd-name"><i>*</i>学校名称</div><div class="vd-form-item__inner"><input name="school" placeholder="请输入"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>毕业时间</div><div class="vd-form-item__inner"><div class="vd-dd" data-layer="cal"><span>请选择</span></div><input type="hidden" name="grad"></div></div>
<div class="vd-line"><div class="vd-name"><i>*</i>期望月薪</div><div class="vd-form-item__inner"><div class="vd-dd" data-layer="salary"><span>请选择</span></div><input type="hidden" name="salary"></div></div>
<button type="submit">预览并提交</button>
</form>
<div class="vd-layer" id="layer-nation"><div class="vd-opt">汉族</div><div class="vd-opt">回族</div><div class="vd-opt">满族</div></div>
<div class="vd-layer" id="layer-origin"><div class="vd-opt">山西省</div><div class="vd-opt">广东省</div></div>
<div class="vd-layer" id="layer-huko"><div class="vd-col" id="huko-p"><div class="vd-opt">山西省</div><div class="vd-opt">广东省</div></div><div class="vd-col" id="huko-c"></div></div>
<div class="vd-layer" id="layer-cal"><table class="vd-cal"><tr><td>2026年</td></tr><tr><td>一</td><td>二</td><td>三</td></tr><tr><td>1</td><td>2</td><td>3</td></tr></table></div>
<div class="vd-layer" id="layer-salary"><div><input class="vd-search" placeholder="输入关键字搜索"></div><div class="vd-hint">请输入关键字搜索</div></div>
<script>
const cities={"山西省":["太原市","阳泉市"],"广东省":["深圳市","广州市"]};
function hideAll(){document.querySelectorAll('.vd-layer').forEach(l=>l.style.display='none');}
function choose(dd,val){dd.querySelector('span').textContent=val;dd.parentElement.querySelector('input[type=hidden]').value=val;hideAll();
  // Site quirk: choosing 籍贯 re-renders the address block and drops what was typed there.
  if(dd.dataset.layer==='origin')document.querySelector('[name=address]').value='';}
document.querySelectorAll('.vd-dd').forEach(dd=>{
  dd.addEventListener('click',e=>{e.stopPropagation();hideAll();const l=document.getElementById('layer-'+dd.dataset.layer);const r=dd.getBoundingClientRect();
    l.style.left=(r.left+scrollX)+'px';l.style.top=(r.bottom+scrollY)+'px';l.style.display='block';l.owner=dd;
    if(dd.dataset.layer==='huko')document.getElementById('huko-c').innerHTML='';});
});
document.querySelectorAll('.vd-layer').forEach(l=>l.addEventListener('mousedown',e=>e.stopPropagation()));
document.querySelectorAll('#layer-nation .vd-opt,#layer-origin .vd-opt').forEach(o=>o.addEventListener('click',e=>{e.stopPropagation();choose(o.closest('.vd-layer').owner,o.textContent);}));
document.querySelectorAll('#huko-p .vd-opt').forEach(o=>o.addEventListener('click',e=>{e.stopPropagation();const p=o.textContent;
  const col=document.getElementById('huko-c');col.innerHTML=cities[p].map(c=>'<div class="vd-opt">'+c+'</div>').join('');
  col.querySelectorAll('.vd-opt').forEach(c=>c.addEventListener('click',ev=>{ev.stopPropagation();choose(document.getElementById('layer-huko').owner,p+' / '+c.textContent);}));}));
document.addEventListener('mousedown',hideAll);
document.getElementById('cv').addEventListener('change',()=>{
  document.querySelector('.vd-attach span').textContent=document.getElementById('cv').files[0].name+' 已上传';
  // The site's resume parser: right name, a truncated phone number and the wrong school.
  setTimeout(()=>{document.querySelector('[name=name]').value='张三';document.querySelector('[name=phone]').value='138 1234 567';
    document.querySelector('[name=school]').value='合成学院';},300);
});
</script></body></html>'''


def add_vendor_form(app):
    @app.get('/apply3', response_class=HTMLResponse)
    def vendor_form():
        return VENDOR_FORM

    return app
