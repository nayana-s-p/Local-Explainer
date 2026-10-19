import json,os,sys,time
from pathlib import Path
base=Path(__file__).resolve().parent.parent
os.environ['EXPLAINER_DATA']=str(base/'.integration-data');sys.path.insert(0,str(base))
from backend.store import *
from backend.jobs import enqueue
p=project(json.loads((base/'docs/integration-result.json').read_text())['project_id']);root=workspace(p['id'])
a=artifact(p,'avatar');data=json.loads(safe(root,a['path']).read_text());folder=safe(root,data['directory'])
(folder/'000002.png').write_bytes(b'incomplete PNG');(folder/'000003.png').unlink()
unchanged=checksum(folder/'000004.png')
j=enqueue(p['id'],'avatar-render')
while True:
 result=get('jobs',j['id'])
 if result['state'] not in ['queued','validating','running','cancelling']:break
 time.sleep(.25)
assert result['state']=='succeeded',result
assert checksum(folder/'000004.png')==unchanged
assert (folder/'000002.png').stat().st_size>100 and (folder/'000003.png').exists()
print('Resume passed: corrupt/missing frames were regenerated; a valid frame remained unchanged.')
