import hashlib, json, os, sqlite3, threading, time, uuid
from pathlib import Path
from fastapi import HTTPException

ROOT = Path(os.environ.get('EXPLAINER_DATA', str(Path.home() / 'Library/Application Support/Local Explainer'))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()

def uid(): return uuid.uuid4().hex

def checksum(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def fingerprint(value): return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def connect():
    c = sqlite3.connect(ROOT / 'app.db', timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    return c

with connect() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT NOT NULL);
    ''')

def records(table):
    with LOCK, connect() as db: return [json.loads(r['data']) for r in db.execute(f'SELECT data FROM {table}')]

def get(table, key):
    with LOCK, connect() as db: row = db.execute(f'SELECT data FROM {table} WHERE '+('key' if table=='settings' else 'id')+'=?', (key,)).fetchone()
    if not row: raise HTTPException(404, 'Item not found.')
    return json.loads(row['data'])

def put(table, value, key=None):
    with LOCK, connect() as db:
        db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (key or value['id'], json.dumps(value)))

def project(pid): return get('projects', pid)

def save(p):
    p['updated_at'] = time.time()
    put('projects', p)
    atomic_json(workspace(p['id']) / 'project.json', p)
    return p

def workspace(pid):
    if len(pid)!=32 or any(c not in '0123456789abcdef' for c in pid): raise HTTPException(400,'Invalid project ID.')
    return safe(ROOT / 'projects', pid)

def safe(root, relative):
    base = Path(root).resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base): raise HTTPException(400,'Path must remain inside the managed workspace.')
    return path

def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uid()+'.tmp')
    temp.write_text(json.dumps(data, indent=2))
    temp.replace(path)

def settings():
    try: return get('settings', 'app')
    except HTTPException:
        return {'blender':'', 'ffmpeg':'', 'ffprobe':'', 'rhubarb':'', 'tts_python':'', 'model_path':'', 'variant':'CustomVoice', 'device':'mps', 'revision':'local'}

def new_project(name):
    pid=uid(); root=workspace(pid)
    for directory in ['source','script','audio','lipsync','renders','output','temp','logs']: (root/directory).mkdir(parents=True, exist_ok=True)
    return save({'id':pid,'name':name[:120] or 'Untitled project','created_at':time.time(),'updated_at':time.time(),'assets':[], 'segments':[], 'pages':[], 'artifacts':[], 'character':None,
        'voice':{'variant':'CustomVoice','language':'English','speaker':'Ryan','instruct':'Speak clearly, warmly, and naturally.'},
        'timeline':{'duration_policy':'require_fit','source_volume':0.2,'narration_volume':1.0,'overlay':{'x':0.72,'y':0.42,'width':0.25,'start':0,'end':None},'avatar_enabled':True},'history':[]})

def stale(p, segment_id=None, kinds=None):
    for a in p['artifacts']:
        if (segment_id is None or a.get('segment_id')==segment_id) and (kinds is None or a['kind'] in kinds): a['stale']=True

def artifact(p, kind, segment_id=None):
    for a in reversed(p['artifacts']):
        if a['kind']==kind and a.get('segment_id')==segment_id and not a['stale']:
            path=safe(workspace(p['id']),a['path'])
            if path.is_file() and checksum(path)==a['checksum']: return a
            a['stale']=True
    return None

def add_artifact(p, path, kind, job_id, segment_id=None, **extra):
    # Keep historical files intact so failed jobs cannot destroy completed output.
    stale(p,segment_id,[kind] if kind!='export' else ['export'])
    a={'id':uid(),'kind':kind,'segment_id':segment_id,'job_id':job_id,'path':str(path.relative_to(workspace(p['id']))),'checksum':checksum(path),'stale':False,'created_at':time.time(),**extra}
    p['artifacts'].append(a)
    return a

def reconcile(p):
    """Validate the dependency chain without discarding unrelated segment artifacts."""
    before=fingerprint(p)
    for s in p['segments']:
        audio=artifact(p,'audio',s['id'])
        if audio and audio.get('inputs')!=fingerprint({'text':s['text'],'voice':p['voice']}):
            audio['stale']=True;audio=None
        if not audio:
            if s.get('duration') is not None:
                s.update(duration=None,status='draft')
                stale(p,s['id'],['cues']);stale(p,None,['avatar','export'])
        else:
            cue=artifact(p,'cues',s['id'])
            if cue and cue.get('inputs')!=audio['checksum']:
                cue['stale']=True;stale(p,None,['avatar','export'])
    for a in p['assets']:
        path=safe(workspace(p['id']),a['path'])
        if not path.is_file(): a['missing']=True
    if p.get('character'):
        c=p['character'];path=safe(workspace(p['id']),c['blend_path'])
        if not path.is_file() or checksum(path)!=c.get('blend_checksum'):
            c['validation']=None;stale(p,None,['avatar','export'])
    if fingerprint(p)!=before: save(p)
    return p
