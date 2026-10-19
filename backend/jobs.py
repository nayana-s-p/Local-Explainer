import concurrent.futures, json, math, os, shutil, signal, subprocess, threading, time, wave, tempfile
from pathlib import Path
from fastapi import HTTPException
from .store import *
from .media import *

EXECUTOR=concurrent.futures.ThreadPoolExecutor(max_workers=1)
PROCESSES={}; LIVE=set()
BASE=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parent.parent))

class Cancelled(Exception): pass

def update(jid, **values):
    with LOCK:
        j=get('jobs',jid); j.update(values); j['heartbeat']=time.time(); put('jobs',j)
    return j

def check(jid):
    if get('jobs',jid)['cancel_requested']: raise Cancelled()

def process(jid,args,stage,env=None):
    check(jid); update(jid,stage=stage,message=stage.replace('_',' ').capitalize())
    # Logs are intentionally omitted: third-party output may contain narration or paths.
    with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as out:
        child=subprocess.Popen(args,stdout=out,stderr=out,env=env,start_new_session=True)
        PROCESSES[jid]=child
        try: started=subprocess.check_output(['/bin/ps','-p',str(child.pid),'-o','lstart='],text=True,stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError: started=None
        update(jid,worker_pid=child.pid,worker_started=started)
        try:
            deadline=time.monotonic()+24*3600
            while child.poll() is None:
                check(jid)
                if time.monotonic()>deadline: raise RuntimeError('Worker exceeded its 24-hour limit.')
                # Read only a machine progress marker; no user content is retained.
                size=os.fstat(out.fileno()).st_size
                tail=os.pread(out.fileno(),min(size,8192),max(0,size-8192)).decode('utf-8',errors='ignore')
                stages=[line.split('EXPLAINER_STAGE ')[-1] for line in tail.splitlines() if line.startswith('EXPLAINER_STAGE ')]
                if stages and stages[-1] in ['load_model','generate_audio']: update(jid,stage=stages[-1],message=stages[-1].replace('_',' ').capitalize())
                markers=[line.split('EXPLAINER_PROGRESS ')[-1] for line in tail.splitlines() if line.startswith('EXPLAINER_PROGRESS ')]
                if markers:
                    try: update(jid,progress=min(.98,float(markers[-1])))
                    except ValueError: pass
                update(jid)
                time.sleep(0.25)
            if child.returncode: raise RuntimeError(f'{stage.replace("_"," ")} failed (exit {child.returncode}). Verify tool versions, input format, and Setup. Diagnostic: {jid[:8]}.')
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(child.pid,signal.SIGKILL); child.wait()
            PROCESSES.pop(jid,None)
            update(jid,worker_pid=None,worker_started=None)

def enqueue(pid,kind,segments=None,retry_of=None):
    with LOCK:
        if pid: project(pid)
        if any(j['project_id']==pid and j['state'] in ['queued','running','validating','cancelling'] for j in records('jobs')): raise HTTPException(409,'This project already has an active job. Wait or cancel it first.')
        j={'id':uid(),'project_id':pid,'type':kind,'segment_ids':segments or [],'state':'queued','stage':'queued','progress':0,'message':'Waiting for local worker','created_at':time.time(),'started_at':None,'finished_at':None,'heartbeat':time.time(),'cancel_requested':False,'error':None,'outputs':[],'retry_of':retry_of}
        put('jobs',j); LIVE.add(j['id']); EXECUTOR.submit(execute,j['id']); return j

def commit(jid, snapshot, callback):
    with LOCK:
        p=project(snapshot['id'])
        # Project editing is blocked during its worker jobs; keep a guard for external callers.
        if fingerprint({k:v for k,v in p.items() if k not in ['artifacts','updated_at']}) != fingerprint({k:v for k,v in snapshot.items() if k not in ['artifacts','updated_at']}): raise RuntimeError('Project changed during processing. Retry with current inputs.')
        callback(p); save(p)
        return p

def execute(jid):
    j=get('jobs',jid)
    try:
        check(jid); update(jid,state='validating',started_at=time.time(),stage='validate_inputs',message='Checking project and dependencies')
        if j['type']=='model-setup': setup_model(jid)
        else:
            p=reconcile(project(j['project_id'])); root=workspace(p['id'])
            selected=[s for s in p['segments'] if not j['segment_ids'] or s['id'] in j['segment_ids']]
            if j['type'] in ['tts','lipsync'] and not selected: raise RuntimeError('Add narration segments first.')
            update(jid,state='running')
            if j['type']=='tts': generate_audio(jid,p,selected)
            elif j['type']=='lipsync': generate_cues(jid,p,selected)
            elif j['type']=='character-validate': validate_character(jid,p)
            elif j['type']=='avatar-render': render_character(jid,p)
            elif j['type']=='export': compose(jid,p)
            else: raise RuntimeError('Unknown job type.')
        check(jid); update(jid,state='succeeded',stage='complete',progress=1,message='Completed',finished_at=time.time())
    except Cancelled: update(jid,state='cancelled',message='Cancelled. Completed artifacts were retained.',finished_at=time.time())
    except HTTPException as e: update(jid,state='failed',error={'code':'INPUT_OR_DEPENDENCY','message':str(e.detail),'diagnostic_id':jid[:8]},message=str(e.detail),finished_at=time.time())
    except Exception as e:
        message=str(e) if isinstance(e,RuntimeError) else 'Processing failed. Check your inputs and dependency setup, then retry.'
        update(jid,state='failed',error={'code':'WORKER_FAILED','message':message,'diagnostic_id':jid[:8]},message=message,finished_at=time.time())
    finally: LIVE.discard(jid)

def wav_duration(path):
    with wave.open(str(path)) as w: return w.getnframes()/w.getframerate()

def generate_audio(jid,p,segments):
    cfg=settings(); python=cfg['tts_python']; model=Path(cfg['model_path'])
    if not python or not Path(python).is_file() or not model_config(cfg): raise RuntimeError('Qwen is not set up. Open Setup to install the isolated runtime and 1.7B model.')
    if p['voice']['language'] not in LANGUAGES: raise RuntimeError('Unsupported language. Choose a supported language in Voice Studio.')
    if p['voice']['variant']!=cfg['variant']: raise RuntimeError('Selected voice variant differs from the installed model. Change Voice Studio or install the selected variant.')
    if any(len(s['text'])>1500 for s in segments): raise RuntimeError('Split narration into segments of 1,500 characters or fewer before generation. Long narration is never silently truncated.')
    root=workspace(p['id'])
    for i,s in enumerate(segments):
        check(jid)
        path=root/'audio'/f'{s["id"]}-{uid()}.wav'; req=root/'temp'/f'{jid}.json'
        atomic_json(req,{'text':s['text'],'voice':p['voice'],'model_path':str(model),'device':cfg['device'],'output':str(path)})
        env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false','HF_HOME':str(ROOT/'model-cache/huggingface')}
        try:
            process(jid,[python,str(BASE/'workers/qwen_worker.py'),str(req)],'generate_audio',env)
        except RuntimeError:
            raise RuntimeError('Qwen generation failed. Verify the complete 1.7B model and tokenizer, the selected variant, and available memory. MPS has not yet been validated on this Mac; select CPU explicitly for a diagnostic test. Diagnostic: '+jid[:8])
        finally: req.unlink(missing_ok=True)
        duration=wav_duration(path)
        runtime_metadata=json.loads(Path(str(path)+'.metadata.json').read_text())
        def completed(current):
            stale(current,s['id'],['audio','cues']); stale(current,None,['avatar','export'])
            add_artifact(current,path,'audio',jid,s['id'],duration=duration,inputs=fingerprint({'text':s['text'],'voice':p['voice']}),model={**{k:cfg[k] for k in ['variant','revision','device']},'config_checksum':checksum(model/'config.json'),'runtime':runtime_metadata},voice=p['voice'])
            target=next(x for x in current['segments'] if x['id']==s['id']); target['duration']=duration; target['status']='ready'
        p=commit(jid,p,completed)
        update(jid,progress=(i+1)/len(segments),message=f'Generated segment {i+1} of {len(segments)}')

def generate_cues(jid,p,segments):
    executable=tool('rhubarb'); root=workspace(p['id'])
    for i,s in enumerate(segments):
        audio=artifact(p,'audio',s['id'])
        if not audio: raise RuntimeError('Generate current audio for every selected segment first.')
        path=root/'lipsync'/f'{s["id"]}-{uid()}.json'
        recognizer='pocketSphinx' if p['voice']['language']=='English' else 'phonetic'
        process(jid,[executable,'-f','json','-r',recognizer,'-o',str(path),str(safe(root,audio['path']))],'analyze_lipsync')
        cues=json.loads(path.read_text()).get('mouthCues',[]); end=0
        for cue in cues:
            if cue['value'] not in 'ABCDEFGHX' or not end<=cue['start']<=cue['end']<=audio['duration']+0.1: raise RuntimeError('Lip-sync worker returned invalid cue timings.')
            end=cue['end']
        if not cues: raise RuntimeError('No mouth cues were generated. Review your narration audio.')
        def completed(current):
            stale(current,None,['avatar','export']); add_artifact(current,path,'cues',jid,s['id'],inputs=audio['checksum'])
        p=commit(jid,p,completed); update(jid,progress=(i+1)/len(segments))

def character_request(p,mode,jid):
    c=p.get('character')
    if not c: raise RuntimeError('Import a prepared character ZIP with manifest.json first.')
    root=workspace(p['id'])
    blend=safe(root,c['blend_path'])
    if not blend.is_file() or checksum(blend)!=c.get('blend_checksum'): raise RuntimeError('Character file is missing or changed. Import and validate the bundle again.')
    req=root/'temp'/f'{jid}-blender.json'; report=root/'temp'/f'{jid}-report.json'
    return c,req,report,{'mode':mode,'manifest':c['manifest'],'report':str(report)}

def validate_character(jid,p):
    c,req,report,data=character_request(p,'validate',jid)
    atomic_json(req,data)
    try:
        process(jid,[tool('blender'),'--background','--disable-autoexec','--python-exit-code','1',str(safe(workspace(p['id']),c['blend_path'])),'--python',str(BASE/'workers/blender_worker.py'),'--',str(req)],'validate_character')
    except RuntimeError:
        if report.exists():
            detail=json.loads(report.read_text()).get('error')
            if detail: raise RuntimeError(detail)
        raise
    result=json.loads(report.read_text())
    if result.get('error'): raise RuntimeError(result['error'])
    if not result.get('valid'): raise RuntimeError('Character validation did not produce a valid report.')
    def completed(current): current['character']['validation']=result
    commit(jid,p,completed)

def video_asset(p):
    v=next((a for a in reversed(p['assets']) if a['kind']=='video'),None)
    if not v: raise RuntimeError('Import a base video first.')
    if checksum(safe(workspace(p['id']),v['path']))!=v['checksum']: raise RuntimeError('The source video is missing or changed. Import it again.')
    return v

def duration(p):
    v=video_asset(p); return max(v['probe']['duration'],max((s['start']+(s.get('duration') or 0) for s in p['segments']),default=0)) if p['timeline']['duration_policy']=='freeze_last_frame' else v['probe']['duration']

def render_signature(p):
    return fingerprint({'character':p['character'],'segments':[{**s,'cue':(artifact(p,'cues',s['id']) or {}).get('checksum')} for s in p['segments']],'video':video_asset(p)['checksum'],'duration':duration(p),'overlay_width':p['timeline']['overlay']['width']})

def render_character(jid,p):
    c,req,report,data=character_request(p,'render',jid)
    if not c.get('validation',{}).get('valid'): raise RuntimeError('Validate the character bundle before rendering.')
    if timeline_issues(p): raise RuntimeError(timeline_issues(p)[0])
    root=workspace(p['id']); v=video_asset(p)['probe']; total=duration(p); signature=render_signature(p)
    out=root/'renders'/signature; out.mkdir(parents=True,exist_ok=True)
    width=max(64,round(v['width']*p['timeline']['overlay']['width'])); width+=width%2
    height=width # Prepared camera controls framing inside a square alpha canvas.
    estimate=math.ceil(total*v['fps'])*width*height*4
    if shutil.disk_usage(root).free<estimate+512*1024**2: raise RuntimeError('Insufficient disk space for transparent frames. Free space or reduce character size.')
    segments=[]
    for s in p['segments']:
        cue=artifact(p,'cues',s['id'])
        if not cue: raise RuntimeError('Generate current mouth cues for every segment first.')
        segments.append({'start':s['start'],'cue_path':str(safe(root,cue['path']))})
    data.update(width=width,height=height,fps=v['fps'],duration=total,segments=segments,output=str(out))
    atomic_json(req,data)
    process(jid,[tool('blender'),'--background','--disable-autoexec','--python-exit-code','1',str(safe(root,c['blend_path'])),'--python',str(BASE/'workers/blender_worker.py'),'--',str(req)],'render_character')
    metadata=json.loads(report.read_text())
    if metadata.get('error'): raise RuntimeError(metadata['error'])
    metadata['signature']=signature; metadata['directory']=str(out.relative_to(root))
    frame_paths=sorted(out.glob('*.png'))
    if len(frame_paths)!=metadata['frames']: raise RuntimeError('Blender produced an incomplete frame sequence.')
    metadata['frame_checksums']=[checksum(f) for f in frame_paths]
    target=out/'frames.json'; atomic_json(target,metadata)
    def completed(current):
        stale(current,None,['export']);add_artifact(current,target,'avatar',jid,inputs=signature)
    commit(jid,p,completed)

def compose(jid,p):
    root=workspace(p['id']); v=video_asset(p); meta=v['probe']; total=duration(p)
    if not p['segments']: raise RuntimeError('Add and generate narration before export.')
    if timeline_issues(p): raise RuntimeError(timeline_issues(p)[0])
    if shutil.disk_usage(root).free<max(512*1024**2,total*meta['width']*meta['height']*0.2): raise RuntimeError('Insufficient free disk space for export.')
    args=[tool('ffmpeg'),'-y','-nostdin','-i',str(safe(root,v['path']))]
    filters=[f'[0:v]setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={max(0,total-meta["duration"]):.6f},fps={meta["frame_rate"]},format=yuv420p[base]']
    next_input=1; video_label='base'
    if p['timeline']['avatar_enabled']:
        avatar=artifact(p,'avatar')
        if not avatar or avatar['inputs']!=render_signature(p): raise RuntimeError('Render the current character before export, or turn off the character overlay explicitly.')
        data=json.loads(safe(root,avatar['path']).read_text()); folder=safe(root,data['directory'])
        for i,digest in enumerate(data['frame_checksums']):
            check(jid)
            frame=folder/f'{i+1:06d}.png'
            if not frame.is_file() or checksum(frame)!=digest: raise RuntimeError('Character frames are missing or corrupted. Render them again.')
        args+=['-framerate',meta['frame_rate'],'-start_number','1','-i',str(folder/'%06d.png')]
        overlay=p['timeline']['overlay']; end=overlay['end'] if overlay['end'] is not None else total
        filters.append(f'[base][{next_input}:v]overlay=x={round(overlay["x"]*meta["width"])}:y={round(overlay["y"]*meta["height"])}:enable=\'between(t,{overlay["start"]},{end})\':eof_action=pass[composite]')
        next_input+=1; video_label='composite'
    labels=[]
    for s in p['segments']:
        a=artifact(p,'audio',s['id'])
        if not a or a['inputs']!=fingerprint({'text':s['text'],'voice':p['voice']}): raise RuntimeError('Generate current audio for every segment before export.')
        args+=['-i',str(safe(root,a['path']))]
        delay=round(s['start']*1000); label=f'n{next_input}'
        filters.append(f'[{next_input}:a]asetpts=PTS-STARTPTS,volume={p["timeline"]["narration_volume"]},adelay={delay}:all=1[{label}]')
        labels.append(f'[{label}]'); next_input+=1
    if meta['audio'] and p['timeline']['source_volume']>0:
        filters.append(f'[0:a]asetpts=PTS-STARTPTS,volume={p["timeline"]["source_volume"]}[sourceaudio]'); labels.append('[sourceaudio]')
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95,apad,atrim=duration={total}[mix]')
    temp=root/'temp'/f'{jid}.mp4'; output=root/'output'/f'explainer-{jid[:8]}.mp4'
    args+=['-filter_complex',';'.join(filters),'-map',f'[{video_label}]','-map','[mix]','-t',str(total),'-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-r',meta['frame_rate'],'-c:a','aac','-b:a','192k','-movflags','+faststart',str(temp)]
    process(jid,args,'compose'); update(jid,progress=0.9,stage='verify_output',message='Verifying exported video')
    result=probe(temp)
    if abs(result['duration']-total)>max(0.1,2/meta['fps']) or result['width']!=meta['width'] or result['height']!=meta['height'] or abs(result['fps']-meta['fps'])>0.01: raise RuntimeError('Export metadata failed verification. Previous exports remain available.')
    temp.replace(output)
    def completed(current): add_artifact(current,output,'export',jid,probe=result,inputs=fingerprint(p),tool_version=run([tool('ffmpeg'),'-version']).splitlines()[0])
    commit(jid,p,completed)
    update(jid,outputs=[str(output.relative_to(root))])

def setup_model(jid):
    if shutil.disk_usage(ROOT).free<8*1024**3: raise RuntimeError('Model setup requires at least 8 GB of free storage for weights and the isolated runtime. Free space and retry.')
    cfg=settings(); python=shutil.which('python3.12') or '/opt/homebrew/bin/python3.12'
    if not Path(python).is_file(): raise RuntimeError('Install Python 3.12 with Homebrew: brew install python@3.12. Then retry setup.')
    environment=ROOT/'tts-runtime'; runtime=environment/'bin/python'
    update(jid,state='running')
    if not runtime.is_file(): process(jid,[python,'-m','venv',str(environment)],'create_runtime')
    process(jid,[str(runtime),'-m','pip','install','qwen-tts==0.1.1','soundfile','huggingface_hub'],'install_runtime')
    model=ROOT/'model-cache'/f'Qwen3-TTS-12Hz-1.7B-{cfg["variant"]}'
    model.parent.mkdir(exist_ok=True)
    # Model downloads happen ONLY in this explicit Setup job.
    code='from huggingface_hub import snapshot_download; import sys; snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2])'
    download_env={**os.environ,'HF_HOME':str(ROOT/'model-cache/huggingface'),'HF_HUB_DISABLE_TELEMETRY':'1'}
    process(jid,[str(runtime),'-c',code,'Qwen/'+model.name,str(model)],'download_model',download_env)
    process(jid,[str(runtime),'-c','from huggingface_hub import snapshot_download; snapshot_download(repo_id="Qwen/Qwen3-TTS-Tokenizer-12Hz")'],'download_tokenizer',download_env)
    cfg.update(tts_python=str(runtime),model_path=str(model)); put('settings',cfg,'app')

for previous in records('jobs'):
    if previous['state'] in ['queued','validating','running','cancelling']:
        # Reap only a process group with the exact recorded PID and creation time.
        pid=previous.get('worker_pid')
        if pid and previous.get('worker_started'):
            try:
                started=subprocess.check_output(['/bin/ps','-p',str(pid),'-o','lstart='],text=True,stderr=subprocess.DEVNULL).strip()
                if started==previous['worker_started'] and os.getpgid(pid)==pid: os.killpg(pid,signal.SIGTERM)
            except (ProcessLookupError,subprocess.CalledProcessError): pass
        previous.update(state='interrupted',message='App closed during processing. Retry to reuse valid checkpoints.',finished_at=time.time())
        put('jobs',previous)
