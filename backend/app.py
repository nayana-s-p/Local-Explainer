import asyncio, copy, json, os, platform, secrets, shutil, subprocess, time, zipfile
from pathlib import Path
from urllib.parse import urlparse
import pymupdf as fitz
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .store import *
from .media import *
from .jobs import enqueue, update, PROCESSES, BASE

TOKEN=os.environ.get('EXPLAINER_TOKEN') or secrets.token_urlsafe(32)
PORT=int(os.environ.get('EXPLAINER_PORT','8765'))
_persist=save
def save(p):
    _persist(p)
    return {**p,'issues':timeline_issues(p)}
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app):
    yield
    for job in records('jobs'):
        if job['state'] in ['queued','validating','running','cancelling']:
            update(job['id'],cancel_requested=True,state='cancelling',message='App is closing; stopping local worker.')
app=FastAPI(title='Local Explainer',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

@app.middleware('http')
async def local_access(request:Request, call_next):
    host=request.headers.get('host','')
    if host not in [f'127.0.0.1:{PORT}',f'localhost:{PORT}','testserver']: return JSONResponse({'detail':'Local access only.'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']: return JSONResponse({'detail':'Cross-origin requests are blocked.'},status_code=403)
    if request.url.path=='/' and secrets.compare_digest(request.query_params.get('token',''),TOKEN):
        response=RedirectResponse('/')
        response.set_cookie('explainer_session',TOKEN,httponly=True,samesite='strict')
        return response
    if not secrets.compare_digest(request.cookies.get('explainer_session',''),TOKEN): return JSONResponse({'detail':'Open the app from its Mac launcher.'},status_code=401)
    if request.method not in ['GET','HEAD'] and request.headers.get('x-local-request')!='1': return JSONResponse({'detail':'Missing local request header.'},status_code=403)
    return await call_next(request)

@app.exception_handler(Exception)
async def errors(request,exc): return JSONResponse({'detail':'The operation failed. Check the input and Setup, then try again.'},status_code=500)

class Name(BaseModel): name:str=Field(min_length=1,max_length=120)
class Delete(BaseModel): confirmation:str
class Segment(BaseModel):
    id:str=Field(pattern=r"^[0-9a-f]{32}$")
    text:str=Field(min_length=1,max_length=20000)
    start:float=Field(ge=0,le=86400)
class Script(BaseModel): segments:list[Segment]
class Voice(BaseModel):
    variant:str='CustomVoice'
    language:str='English'
    speaker:str='Ryan'
    instruct:str=Field(default='',max_length=2000)
class Overlay(BaseModel):
    x:float=Field(ge=0,le=1); y:float=Field(ge=0,le=1); width:float=Field(ge=.05,le=1)
    start:float=Field(ge=0); end:float|None=None
class Timeline(BaseModel):
    duration_policy:str
    source_volume:float=Field(ge=0,le=2)
    narration_volume:float=Field(ge=0,le=2)
    avatar_enabled:bool
    overlay:Overlay
class JobRequest(BaseModel): segment_ids:list[str]=[]
class SettingsInput(BaseModel):
    blender:str=''; ffmpeg:str=''; ffprobe:str=''; rhubarb:str=''; tts_python:str=''; model_path:str=''
    variant:str='CustomVoice'; device:str='mps'; revision:str='local'

def editable(pid):
    if any(j['project_id']==pid and j['state'] in ['queued','running','validating','cancelling'] for j in records('jobs')): raise HTTPException(409,'A job is using this project. Wait or cancel it before editing.')
    return project(pid)

@app.get('/api/v1/health')
def health(): return {'version':'0.1.0','status':'ready','active_workers':len(PROCESSES)}

@app.get('/api/v1/capabilities')
def capabilities():
    deps={}
    for name in ['ffmpeg','ffprobe','blender','rhubarb']:
        try:
            path=tool(name); args=[path,'-version'] if name.startswith('ff') else [path,'--version']
            deps[name]={'available':True,'path':path,'version':run(args,timeout=10).splitlines()[0]}
        except Exception: deps[name]={'available':False,'path':'','version':''}
    cfg=settings(); m=Path(cfg['model_path']) if cfg['model_path'] else None
    try: memory=int(subprocess.check_output(['sysctl','-n','hw.memsize']))/1024**3
    except Exception: memory=None
    return {'os':platform.system(),'architecture':platform.machine(),'memory_gb':memory,'free_disk_gb':round(shutil.disk_usage(ROOT).free/1024**3,1),'dependencies':deps,'model_ready':bool(model_config(cfg) and Path(cfg['tts_python']).is_file()),'languages':LANGUAGES,'speakers':SPEAKERS,'settings':cfg,'ocr_available':bool(shutil.which('tesseract'))}

@app.get('/api/v1/settings')
def read_settings(): return settings()
@app.put('/api/v1/settings')
def write_settings(data:SettingsInput):
    if any(j['state'] in ['queued','running','validating','cancelling'] for j in records('jobs')): raise HTTPException(409,'Wait for active jobs before changing dependency settings.')
    if data.variant not in ['CustomVoice','VoiceDesign'] or data.device not in ['mps','cpu']: raise HTTPException(422,'Choose CustomVoice or VoiceDesign, and MPS or CPU.')
    put('settings',data.model_dump(),'app'); return data
@app.post('/api/v1/setup/model')
def model_setup(): return enqueue(None,'model-setup')

@app.get('/api/v1/projects')
def projects(): return sorted(records('projects'),key=lambda p:p['updated_at'],reverse=True)
@app.post('/api/v1/projects')
def create(data:Name): return new_project(data.name)
@app.post('/api/v1/samples')
def sample_project():
    sample=BASE/'sample-project'
    if not (sample/'sage-character.zip').is_file(): raise HTTPException(422,'Sample assets are not included in this build.')
    p=new_project('Sage presenter · Sample');pid=p['id']
    for kind,name in [('video','demo.mp4'),('character','sage-character.zip')]:
        with (sample/name).open('rb') as f: import_asset(pid,kind,UploadFile(file=f,filename=name),None)
    s={'id':uid(),'text':'This is the sample presenter. Your words, on your Mac.','start':.2,'duration':None,'status':'draft'}
    p=project(pid);p['segments']=[s];p['sample_note']='Sample WAV created with macOS system speech for pipeline testing. Generate Qwen audio in Voice Studio to evaluate the required model.';save(p)
    with (sample/'fixture.wav').open('rb') as f: import_asset(pid,'audio',UploadFile(file=f,filename='Sample fixture · macOS speech.wav'),s['id'])
    p=project(pid);p['timeline']['duration_policy']='freeze_last_frame';return save(p)

@app.get('/api/v1/projects/{pid}')
def read_project(pid:str):
    p=reconcile(project(pid)); p['issues']=timeline_issues(p)
    for a in p['artifacts']:
        if not safe(workspace(pid),a['path']).is_file(): a['stale']=True
    return p
@app.patch('/api/v1/projects/{pid}')
def rename(pid:str,data:Name): p=editable(pid); p['name']=data.name; return save(p)
@app.post('/api/v1/projects/{pid}/duplicate')
def duplicate(pid:str):
    p=editable(pid); new=new_project(p['name']+' copy'); root=workspace(new['id'])
    shutil.copytree(workspace(pid),root,dirs_exist_ok=True)
    p['id']=new['id']; p['created_at']=time.time(); p['name']=new['name']; p['history']=[]
    # Frame manifests contain relative paths, so copied intermediates remain portable.
    return save(p)
@app.delete('/api/v1/projects/{pid}')
def delete(pid:str,data:Delete):
    p=editable(pid)
    if data.confirmation!=p['name']: raise HTTPException(422,'Enter the project name to confirm deletion.')
    shutil.rmtree(workspace(pid))
    with LOCK,connect() as db:
        db.execute('DELETE FROM projects WHERE id=?',(pid,))
        for j in records('jobs'):
            if j['project_id']==pid: db.execute('DELETE FROM jobs WHERE id=?',(j['id'],))
    return {'deleted':True}

@app.post('/api/v1/projects/{pid}/assets')
def import_asset(pid:str,kind:str,file:UploadFile=File(...),segment_id:str|None=None):
    p=editable(pid); root=workspace(pid)
    if kind not in ['pdf','video','character','audio']: raise HTTPException(422,'Unsupported asset type.')
    extension={'pdf':'.pdf','character':'.zip','audio':'.wav'}.get(kind,Path(file.filename or '').suffix.lower())
    if kind=='video' and extension not in ['.mp4','.mov','.mkv','.webm','.avi','.m4v']: raise HTTPException(422,'Choose MP4, MOV, MKV, WebM, AVI, or M4V.')
    path=root/'source'/f'{uid()}{extension}'; size=0
    try:
        with path.open('wb') as out:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>4*1024**3: raise HTTPException(422,'Import limit is 4 GB per file.')
                if shutil.disk_usage(root).free< len(chunk)+256*1024**2: raise HTTPException(422,'Not enough disk space for import.')
                out.write(chunk)
        a={'id':uid(),'kind':kind,'name':Path(file.filename or 'Imported asset').name,'path':str(path.relative_to(root)),'size':size,'checksum':checksum(path),'created_at':time.time()}
        if kind=='pdf':
            with fitz.open(path) as doc:
                if not doc.is_pdf or doc.needs_pass: raise HTTPException(422,'Choose an unencrypted PDF.')
                a['page_count']=len(doc)
        elif kind=='video':
            a['probe']=probe(path); stale(p,None,['avatar','export'])
        elif kind=='character':
            folder=root/'source'/f'character-{uid()}'; folder.mkdir()
            try: manifest,manifest_path,blend=unpack_bundle(path,folder)
            except Exception: shutil.rmtree(folder); raise
            p['character']={'manifest':manifest,'manifest_path':str(manifest_path.relative_to(root)),'blend_path':str(blend.relative_to(root)),'blend_checksum':checksum(blend),'bundle_checksum':a['checksum'],'validation':None}
            stale(p,None,['avatar','export'])
        elif kind=='audio':
            s=next((s for s in p['segments'] if s['id']==segment_id),None)
            if not s: raise HTTPException(422,'Select a segment for replacement audio.')
            from .jobs import wav_duration
            try: d=wav_duration(path)
            except Exception: raise HTTPException(422,'Replacement audio must be an uncompressed PCM WAV.')
            add_artifact(p,path,'audio','manual-import',s['id'],duration=d,inputs=fingerprint({'text':s['text'],'voice':p['voice']}),voice=p['voice'],model={'source':'user-supplied WAV'})
            s.update(duration=d,status='ready'); stale(p,s['id'],['cues']); stale(p,None,['avatar','export'])
        p['assets'].append(a); return save(p)
    except (zipfile.BadZipFile,json.JSONDecodeError,UnicodeDecodeError,fitz.FileDataError):
        path.unlink(missing_ok=True)
        raise HTTPException(422,'The imported file is malformed. Choose a readable PDF, PCM WAV, or a character ZIP containing valid manifest.json and a Blender project.')
    except Exception:
        path.unlink(missing_ok=True); raise

@app.post('/api/v1/projects/{pid}/script/extract')
def extract(pid:str,ocr:bool=False):
    p=editable(pid); a=next((a for a in reversed(p['assets']) if a['kind']=='pdf'),None)
    if not a: raise HTTPException(422,'Import a PDF first.')
    if p['segments']: raise HTTPException(409,'The script already has edits. Use a new project to re-extract without losing them.')
    pages=[]; segments=[]
    with fitz.open(safe(workspace(pid),a['path'])) as doc:
        for i,page in enumerate(doc):
            text=page.get_text(sort=True).strip(); status='extracted'
            if not text and ocr:
                if not shutil.which('tesseract'): raise HTTPException(422,'Install Tesseract to use local OCR.')
                try: text=page.get_text(textpage=page.get_textpage_ocr(language='eng',dpi=200)).strip(); status='ocr-review'
                except Exception: status='ocr-failed'
            if not text: status='empty-review'
            pages.append({'page':i+1,'text':text,'status':status})
            for paragraph in text.split('\n\n'):
                if paragraph.strip(): segments.append({'id':uid(),'text':paragraph.strip(),'start':0,'duration':None,'status':'draft','page':i+1})
    p['pages']=pages; p['segments']=segments
    atomic_json(workspace(pid)/'script/extracted-pages.json',pages); return save(p)

@app.put('/api/v1/projects/{pid}/script')
def save_script(pid:str,data:Script):
    p=editable(pid); old={s['id']:s for s in p['segments']}
    if len({s.id for s in data.segments})!=len(data.segments): raise HTTPException(422,'Segment IDs must be unique.')
    p['history']=(p['history']+[{'segments':copy.deepcopy(p['segments']),'timeline':copy.deepcopy(p['timeline'])}])[-30:]
    result=[]
    for s in data.segments:
        previous=old.get(s.id,{}); value={**previous,**s.model_dump()}
        if previous.get('text')!=s.text:
            stale(p,s.id,['audio','cues']); value.update(duration=None,status='draft'); stale(p,None,['avatar','export'])
        elif previous.get('start')!=s.start: stale(p,None,['avatar','export'])
        result.append(value)
    for sid in set(old)-{s.id for s in data.segments}: stale(p,sid,['audio','cues']); stale(p,None,['avatar','export'])
    p['segments']=result; return save(p)
@app.post('/api/v1/projects/{pid}/undo')
def undo(pid:str):
    p=editable(pid)
    if not p['history']: raise HTTPException(422,'No saved edit to undo.')
    previous=p['history'].pop(); p.update(previous); stale(p)
    for s in p['segments']: s.update(duration=None,status='draft')
    return save(p)
@app.put('/api/v1/projects/{pid}/voice')
def voice(pid:str,data:Voice):
    p=editable(pid)
    if data.language not in LANGUAGES: raise HTTPException(422,'Qwen3-TTS does not support this language. Choose a language from the list.')
    if data.variant not in ['CustomVoice','VoiceDesign']: raise HTTPException(422,'Choose CustomVoice or VoiceDesign.')
    if data.variant=='CustomVoice' and data.speaker not in SPEAKERS: raise HTTPException(422,'Unsupported speaker.')
    if p['voice']!=data.model_dump():
        p['voice']=data.model_dump(); stale(p)
        for s in p['segments']: s.update(duration=None,status='draft')
    return save(p)
@app.put('/api/v1/projects/{pid}/timeline')
def timeline(pid:str,data:Timeline):
    p=editable(pid)
    if data.duration_policy not in ['require_fit','freeze_last_frame']: raise HTTPException(422,'Choose a valid duration policy.')
    if data.overlay.end is not None and data.overlay.end<=data.overlay.start: raise HTTPException(422,'Overlay end must be after its start.')
    p['history']=(p['history']+[{'segments':copy.deepcopy(p['segments']),'timeline':copy.deepcopy(p['timeline'])}])[-30:]
    if p['timeline']['overlay']['width']!=data.overlay.width: stale(p,None,['avatar'])
    p['timeline']=data.model_dump(); stale(p,None,['export']); return save(p)

@app.post('/api/v1/projects/{pid}/jobs/{kind}')
def start_job(pid:str,kind:str,data:JobRequest):
    if kind not in ['tts','lipsync','character-validate','avatar-render','export']: raise HTTPException(422,'Unsupported job.')
    return enqueue(pid,kind,data.segment_ids)
@app.get('/api/v1/jobs')
def jobs(): return sorted(records('jobs'),key=lambda j:j['created_at'],reverse=True)
@app.get('/api/v1/jobs/events')
async def events(request:Request):
    async def stream():
        previous=''
        while not await request.is_disconnected():
            current=json.dumps(jobs())
            if current!=previous: yield 'data: '+current+'\n\n'; previous=current
            else: yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})
@app.get('/api/v1/jobs/{jid}')
def job(jid:str): return get('jobs',jid)
@app.post('/api/v1/jobs/{jid}/cancel')
def cancel(jid:str):
    j=get('jobs',jid)
    if j['state'] not in ['queued','validating','running','cancelling']: raise HTTPException(409,'This job has already finished.')
    return update(jid,cancel_requested=True,state='cancelling',message='Stopping local worker…')
@app.post('/api/v1/jobs/{jid}/retry')
def retry(jid:str):
    j=get('jobs',jid)
    if j['state'] not in ['failed','cancelled','interrupted']: raise HTTPException(409,'This job cannot be retried.')
    p=project(j['project_id']) if j['project_id'] else None
    segments=j['segment_ids']
    if p and j['type'] in ['tts','lipsync']:
        kind='audio' if j['type']=='tts' else 'cues'
        selected=[s for s in p['segments'] if not segments or s['id'] in segments]
        segments=[s['id'] for s in selected if not artifact(p,kind,s['id'])]
        if not segments: raise HTTPException(409,'All segment artifacts are already complete and valid.')
    return enqueue(j['project_id'],j['type'],segments,retry_of=jid)

@app.get('/api/v1/projects/{pid}/files/{aid}')
def file(pid:str,aid:str):
    p=project(pid); item=next((a for a in p['assets']+p['artifacts'] if a['id']==aid),None)
    if not item: raise HTTPException(404,'File not found.')
    path=safe(workspace(pid),item['path'])
    if not path.is_file(): raise HTTPException(404,'File is missing.')
    return FileResponse(path,media_type='video/mp4' if path.suffix=='.mp4' else None)
@app.get('/api/v1/projects/{pid}/avatar-preview')
def avatar_preview(pid:str,time:float=0):
    p=project(pid); a=artifact(p,'avatar')
    if not a: raise HTTPException(404,'Render a current character preview first.')
    data=json.loads(safe(workspace(pid),a['path']).read_text()); frame=min(data['frames'],max(1,round(time*data['fps'])+1))
    return FileResponse(safe(workspace(pid),data['directory'])/f'{frame:06d}.png')
@app.post('/api/v1/projects/{pid}/reveal')
def reveal(pid:str):
    subprocess.Popen(['/usr/bin/open',str(workspace(pid)/'output')]); return {'opened':True}
@app.get('/api/v1/projects/{pid}/archive')
def archive(pid:str):
    p=editable(pid); target=ROOT/'archives'/f'{pid}.zip'; target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for path in workspace(pid).rglob('*'):
            if path.is_file() and not path.is_symlink() and 'temp' not in path.relative_to(workspace(pid)).parts: z.write(path,path.relative_to(workspace(pid)))
    return FileResponse(target,filename=p['name']+'.zip')

static=BASE/'frontend/dist'
if static.exists(): app.mount('/',StaticFiles(directory=static,html=True),name='ui')
