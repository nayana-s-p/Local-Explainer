"""Actual Blender / Rhubarb / FFmpeg vertical slice, with explicitly imported fixture WAV."""
import json, os, subprocess, sys, time, zipfile
from pathlib import Path
base=Path(__file__).resolve().parent.parent
os.environ['EXPLAINER_DATA']=str(base/'.integration-data');os.environ['EXPLAINER_TOKEN']='integration'
sys.path.insert(0,str(base))
from fastapi.testclient import TestClient
from backend.app import app
from backend.media import tool
from backend.store import project,artifact,workspace

assets=base/'sample-project';assets.mkdir(exist_ok=True)
subprocess.run([tool('ffmpeg'),'-y','-f','lavfi','-i','testsrc2=s=640x360:r=24:d=4','-f','lavfi','-i','sine=frequency=180:duration=4','-c:v','libx264','-c:a','aac','-shortest',str(assets/'demo.mp4')],capture_output=True,check=True)
# The fixture is clearly marked, and is not a substitute TTS provider in the app.
subprocess.run(['/usr/bin/say','-o',str(assets/'fixture.aiff'),'This is the sample presenter. Your words, on your Mac.'],check=True)
subprocess.run([tool('ffmpeg'),'-y','-i',str(assets/'fixture.aiff'),'-ar','24000','-ac','1',str(assets/'fixture.wav')],capture_output=True,check=True)
with zipfile.ZipFile(assets/'sage-character.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name in ['manifest.json','presenter.blend']: z.write(base/'sample-character'/name,name)
with TestClient(app,headers={'X-Local-Request':'1'}) as c:
 c.get('/?token=integration')
 p=c.post('/api/v1/projects',json={'name':'Integration · Sage presenter'}).json();pid=p['id'];prefix='/api/v1/projects/'+pid
 for kind,name in [('video','demo.mp4'),('character','sage-character.zip')]:
  result=c.post(prefix+'/assets?kind='+kind,files={'file':(name,(assets/name).read_bytes())});assert result.status_code==200,result.text
 sid='a'*32
 c.put(prefix+'/script',json={'segments':[{'id':sid,'text':'This is the sample presenter. Your words, on your Mac.','start':.2}]})
 result=c.post(prefix+'/assets?kind=audio&segment_id='+sid,files={'file':('fixture.wav',(assets/'fixture.wav').read_bytes())});assert result.status_code==200,result.text
 t=p['timeline'];t['duration_policy']='freeze_last_frame';t['overlay'].update(x=.69,y=.40,width=.30)
 c.put(prefix+'/timeline',json=t)
 for kind in ['character-validate','lipsync','avatar-render','export']:
  response=c.post(prefix+'/jobs/'+kind,json={});assert response.status_code==200,response.text
  jid=response.json()['id']
  while True:
   j=c.get('/api/v1/jobs/'+jid).json()
   if j['state'] not in ['queued','running','validating','cancelling']:break
   time.sleep(.4)
  print(kind, j['state'],j['message'],flush=True)
  assert j['state']=='succeeded',j
 current=project(pid);a=artifact(current,'export');output=workspace(pid)/a['path']
 (base/'docs/integration-result.json').write_text(json.dumps({'project_id':pid,'output':str(output),'metadata':a['probe'],'jobs':c.get('/api/v1/jobs').json()},indent=2))
 import shutil
 shutil.copy2(output,assets/'verified-sample.mp4')
 print('Verified output:',output,flush=True)
