import httpx,json,time,os
from pathlib import Path
with httpx.Client(base_url='http://127.0.0.1:8766',headers={'X-Local-Request':'1'},follow_redirects=True,timeout=30) as c:
 for _ in range(100):
  try:
   if c.get('/?token=package-smoke').status_code==200:break
  except httpx.ConnectError:pass
  time.sleep(.1)
 caps=c.get('/api/v1/capabilities').json()
 assert all(caps['dependencies'][x]['available'] for x in ['ffmpeg','ffprobe','blender','rhubarb']),caps
 r=c.post('/api/v1/samples');assert r.status_code==200,r.text
 p=r.json();prefix='/api/v1/projects/'+p['id']
 for kind in ['character-validate','lipsync','avatar-render','export']:
  response=c.post(prefix+'/jobs/'+kind,json={});assert response.status_code==200,response.text
  j=response.json()
  while j['state'] in ['queued','validating','running','cancelling']:
   time.sleep(.5);j=c.get('/api/v1/jobs/'+j['id']).json()
  print('Packaged',kind,j['state'],flush=True);assert j['state']=='succeeded',j
 final=c.get(prefix).json();a=next(a for a in reversed(final['artifacts']) if a['kind']=='export' and not a['stale'])
 output=c.get(prefix+'/files/'+a['id']);assert output.status_code==200 and len(output.content)>1000
 Path('docs/package-result.json').write_text(json.dumps({'dependencies':caps['dependencies'],'output_probe':a['probe'],'project_id':p['id']},indent=2))
 print('Packaged API and actual local pipeline passed.',flush=True)
