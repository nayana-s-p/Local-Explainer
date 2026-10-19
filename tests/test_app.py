import io, json, math, os, struct, time, wave, zipfile
from pathlib import Path
import pytest
os.environ.setdefault('EXPLAINER_DATA',str(Path(__file__).resolve().parent.parent/'.pytest-data'))
os.environ['EXPLAINER_TOKEN']='test-token'
from fastapi.testclient import TestClient
from backend.app import app
from backend.store import *
from backend.media import timeline_issues, tool
from backend.jobs import enqueue

@pytest.fixture
def client():
    with TestClient(app,headers={'X-Local-Request':'1'}) as c:
        c.get('/?token=test-token'); yield c

@pytest.fixture
def p(client): return client.post('/api/v1/projects',json={'name':'Test project'}).json()

def request_path(p,path): return '/api/v1/projects/'+p['id']+path

def test_local_auth_and_origin(client):
    assert TestClient(app).get('/api/v1/projects').status_code==401
    assert client.post('/api/v1/projects',json={'name':'x'},headers={'origin':'https://evil.test'}).status_code==403
    assert client.get('/api/v1/projects',headers={'host':'evil.test'}).status_code==403
    assert client.post('/api/v1/projects',json={'name':'x'},headers={'x-local-request':'0'}).status_code==403

def test_pdf_edit_and_reopen(client,p):
    import fitz
    doc=fitz.open()
    for text in ['First page narration.','Second page narration.']:
        page=doc.new_page(); page.insert_text((70,70),text)
    result=client.post(request_path(p,'/assets?kind=pdf'),files={'file':('script.pdf',doc.tobytes(),'application/pdf')})
    assert result.status_code==200
    result=client.post(request_path(p,'/script/extract')).json()
    assert len(result['pages'])==2 and len(result['segments'])==2
    original=result['segments']; original[0]['text']='Edited text persists.'; original[1]['start']=12.4
    assert client.put(request_path(p,'/script'),json={'segments':original}).status_code==200
    with TestClient(app,headers={'X-Local-Request':'1'}) as reopened:
        reopened.get('/?token=test-token'); saved=reopened.get(request_path(p,'')).json()
    assert saved['segments'][0]['text']=='Edited text persists.' and saved['segments'][1]['start']==12.4
    assert saved['segments'][1]['id']==original[1]['id']

def test_language_and_path_validation(client,p,tmp_path):
    result=client.put(request_path(p,'/voice'),json={**p['voice'],'language':'Hindi'})
    assert result.status_code==422 and 'does not support' in result.text
    bad=client.put(request_path(p,'/script'),json={'segments':[{'id':'../../escape','text':'Hello','start':0}]})
    assert bad.status_code==422
    with pytest.raises(Exception): safe(tmp_path,'../escape')
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w') as z: z.writestr('../../escape','owned')
    assert client.post(request_path(p,'/assets?kind=character'),files={'file':('bad.zip',payload.getvalue())}).status_code==400
    assert not (workspace(p['id']).parent/'escape').exists()

def test_invalidation_is_per_segment(client,p):
    ids=[uid(),uid(),uid()]
    ss=[{'id':sid,'text':'Hello '+str(i),'start':i*3} for i,sid in enumerate(ids)]
    client.put(request_path(p,'/script'),json={'segments':ss})
    current=project(p['id'])
    for i,sid in enumerate(ids):
        path=workspace(p['id'])/'audio'/f'{sid}.wav'; path.write_bytes(bytes([i]))
        add_artifact(current,path,'audio','test',sid)
        cue=workspace(p['id'])/'lipsync'/f'{sid}.json'; cue.write_text('{}');add_artifact(current,cue,'cues','test',sid)
    save(current); ss[1]['text']='Only this segment changed'
    changed=client.put(request_path(p,'/script'),json={'segments':ss}).json()
    for a in changed['artifacts']: assert a['stale']==(a['segment_id']==ids[1])

def test_overlap_and_explicit_extension():
    p={'assets':[{'kind':'video','probe':{'duration':3}}],'segments':[{'id':'a','start':0,'duration':4},{'id':'b','start':2,'duration':1}],'timeline':{'duration_policy':'require_fit'}}
    assert len(timeline_issues(p))==2
    p['timeline']['duration_policy']='freeze_last_frame'; assert len(timeline_issues(p))==1
    p['segments'][1]['start']=5; assert not timeline_issues(p)

def wait_job(client,jid):
    for _ in range(120):
        j=client.get('/api/v1/jobs/'+jid).json()
        if j['state'] not in ['queued','validating','running','cancelling']:return j
        time.sleep(.1)
    pytest.fail('Job did not finish')

def test_real_ffmpeg_export_and_previous_output(client,p,tmp_path):
    import subprocess
    video=tmp_path/'source.mp4'
    subprocess.run([tool('ffmpeg'),'-y','-f','lavfi','-i','color=c=navy:s=320x180:r=24:d=2','-f','lavfi','-i','sine=frequency=220:duration=2','-c:v','libx264','-c:a','aac','-shortest',str(video)],capture_output=True,check=True)
    assert client.post(request_path(p,'/assets?kind=video'),files={'file':('source.mp4',video.read_bytes())}).status_code==200
    sid=uid();client.put(request_path(p,'/script'),json={'segments':[{'id':sid,'text':'Audio replacement fixture','start':.5}]})
    wav=io.BytesIO()
    with wave.open(wav,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
        out.writeframes(b''.join(struct.pack('<h',round(4000*math.sin(i/24000*math.pi*880))) for i in range(24000)))
    result=client.post(request_path(p,'/assets?kind=audio&segment_id='+sid),files={'file':('narration.wav',wav.getvalue())})
    assert result.status_code==200
    t=p['timeline'];t['avatar_enabled']=False;t['source_volume']=0
    client.put(request_path(p,'/timeline'),json=t)
    j=client.post(request_path(p,'/jobs/export'),json={}).json(); done=wait_job(client,j['id'])
    assert done['state']=='succeeded',done
    final=project(p['id']); a=artifact(final,'export');assert a['probe']['width']==320 and a['probe']['fps']==24 and abs(a['probe']['duration']-2)<.1
    path=workspace(p['id'])/a['path']; before=checksum(path)
    sound=subprocess.run([tool('ffmpeg'),'-i',str(path),'-af','silencedetect=noise=-45dB:d=0.1','-f','null','-'],capture_output=True,text=True).stderr
    import re
    silence_end=float(re.search(r'silence_end: ([0-9.]+)',sound).group(1))
    assert abs(silence_end-.5)<.1, sound
    # Missing character blocks the next export while preserving the previous file.
    t['avatar_enabled']=True;client.put(request_path(p,'/timeline'),json=t)
    failed=client.post(request_path(p,'/jobs/export'),json={}).json(); assert wait_job(client,failed['id'])['state']=='failed'
    assert checksum(path)==before

def test_delete_requires_confirmation(client,p):
    assert client.request('DELETE',request_path(p,''),json={'confirmation':'wrong'}).status_code==422
    assert workspace(p['id']).is_dir()
    assert client.request('DELETE',request_path(p,''),json={'confirmation':p['name']}).status_code==200
    assert not workspace(p['id']).exists()

def test_cancel_terminates_worker_and_keeps_files(client,p,monkeypatch):
    import backend.jobs as worker
    import sys
    sid=uid();client.put(request_path(p,'/script'),json={'segments':[{'id':sid,'text':'Cancel test','start':0}]})
    completed=workspace(p['id'])/'audio/completed.wav';completed.write_bytes(b'valid prior intermediate')
    def slow(jid,p,segments): worker.process(jid,[sys.executable,'-c','import time; time.sleep(30)'],'generate_audio')
    monkeypatch.setattr(worker,'generate_audio',slow)
    j=client.post(request_path(p,'/jobs/tts'),json={}).json()
    for _ in range(100):
        if j['id'] in worker.PROCESSES:break
        time.sleep(.02)
    child=worker.PROCESSES[j['id']];assert child.poll() is None
    client.post('/api/v1/jobs/'+j['id']+'/cancel')
    done=wait_job(client,j['id']);assert done['state']=='cancelled'
    assert child.poll() is not None and completed.exists()

def test_restart_marks_interrupted(tmp_path):
    import subprocess,sys
    env={**os.environ,'EXPLAINER_DATA':str(tmp_path)}
    subprocess.run([sys.executable,'-c',"from backend.store import *; put('jobs',{'id':'restart-test','state':'running'})"],env=env,check=True)
    result=subprocess.run([sys.executable,'-c',"import backend.jobs; from backend.store import get; print(get('jobs','restart-test')['state'])"],env=env,capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='interrupted'

def test_corrupt_audio_invalidates_only_dependents(client,p):
    ids=[uid(),uid()]
    current=project(p['id']);current['segments']=[{'id':sid,'text':'Integrity test','start':i*2,'duration':1,'status':'ready'} for i,sid in enumerate(ids)]
    for sid in ids:
        path=workspace(p['id'])/'audio'/f'{sid}.wav';path.write_bytes(b'original audio')
        a=add_artifact(current,path,'audio','test',sid,inputs=fingerprint({'text':'Integrity test','voice':current['voice']}))
        cue=workspace(p['id'])/'lipsync'/f'{sid}.json';cue.write_text('{}');add_artifact(current,cue,'cues','test',sid,inputs=a['checksum'])
    save(current)
    (workspace(p['id'])/'audio'/f'{ids[0]}.wav').write_bytes(b'corrupted')
    read=client.get(request_path(p,'')).json()
    assert read['segments'][0]['duration'] is None and read['segments'][1]['duration']==1
    for a in read['artifacts']: assert a['stale']==(a['segment_id']==ids[0])

def test_low_disk_blocks_model_setup(monkeypatch):
    import backend.jobs as worker
    from collections import namedtuple
    Usage=namedtuple('Usage','total used free')
    monkeypatch.setattr(worker.shutil,'disk_usage',lambda _:Usage(100,99,1))
    with pytest.raises(RuntimeError,match='free storage'): worker.setup_model('unused')

def test_model_variant_cannot_substitute_small_weights(tmp_path):
    from backend.media import model_config
    (tmp_path/'config.json').write_text(json.dumps({'model_type':'qwen3_tts','tts_model_size':'0b6','tts_model_type':'custom_voice'}))
    (tmp_path/'model.safetensors').write_bytes(b'fixture')
    assert model_config({'model_path':str(tmp_path),'variant':'CustomVoice'}) is None

def test_real_blender_names_missing_mapping(client,p):
    source=Path(__file__).resolve().parent.parent/'sample-project/sage-character.zip'
    if not source.exists():pytest.skip('Generate the sample character fixture first.')
    try: tool('blender')
    except Exception:pytest.skip('Blender is not installed.')
    out=io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(out,'w') as modified:
        for item in original.infolist():
            data=original.read(item)
            if item.filename=='manifest.json':
                m=json.loads(data);m['viseme_map']['X']='MissingNeutralPose';data=json.dumps(m).encode()
            modified.writestr(item.filename,data)
    result=client.post(request_path(p,'/assets?kind=character'),files={'file':('invalid-character.zip',out.getvalue())})
    assert result.status_code==200,result.text
    j=client.post(request_path(p,'/jobs/character-validate'),json={}).json()
    done=wait_job(client,j['id']);assert done['state']=='failed',done
    assert 'MissingNeutralPose' in done['error']['message']

def test_malformed_imports_are_actionable(client,p):
    for kind,name,data in [('pdf','bad.pdf',b'not a PDF'),('character','bad.zip',b'not a ZIP')]:
        result=client.post(request_path(p,'/assets?kind='+kind),files={'file':(name,data)})
        assert result.status_code==422 and 'malformed' in result.text
    contents=io.BytesIO()
    with zipfile.ZipFile(contents,'w') as z:z.writestr('manifest.json','[]')
    result=client.post(request_path(p,'/assets?kind=character'),files={'file':('bad-schema.zip',contents.getvalue())})
    assert result.status_code==422 and 'JSON object' in result.text
