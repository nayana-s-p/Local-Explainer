import json, shutil, subprocess, zipfile
from pathlib import Path
from fastapi import HTTPException
from .store import safe, settings

LANGUAGES=['English','Chinese','Japanese','Korean','German','French','Russian','Portuguese','Spanish','Italian']
SPEAKERS=['Ryan','Aiden','Vivian','Serena','Uncle_Fu','Dylan','Eric','Ono_Anna','Sohee']

def tool(name):
    configured=settings().get(name)
    if configured and Path(configured).is_file(): return configured
    if name=='rhubarb':
        bundled=Path(__import__('os').environ.get('EXPLAINER_BUNDLED_TOOLS',str(Path(__file__).resolve().parent.parent/'tools')))
        for candidate in [bundled/'rhubarb/rhubarb',bundled/'Rhubarb-Lip-Sync-1.14.0-macOS/rhubarb']:
            if candidate.is_file(): return str(candidate)
    if name=='ffprobe':
        base=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parent.parent))
        if (base/'ffprobe').is_file(): return str(base/'ffprobe')
    found=shutil.which(name)
    if found: return found
    if name=='blender':
        path='/Applications/Blender.app/Contents/MacOS/Blender'
        if Path(path).is_file(): return path
    if name=='ffmpeg':
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    if name=='ffprobe':
        path='/opt/homebrew/bin/ffprobe'
        if Path(path).is_file(): return path
    raise HTTPException(422, f'{name} is missing. Open Setup and configure its executable.')

def run(args, timeout=120):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if result.returncode: raise HTTPException(422,'The media tool rejected this input. Check the format and dependency setup.')
    return result.stdout

def probe(path):
    data=json.loads(run([tool('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',str(path)]))
    video=next((s for s in data['streams'] if s['codec_type']=='video'),None)
    if not video: raise HTTPException(422,'No video stream found. Choose a supported video.')
    rate=video.get('avg_frame_rate') or video.get('r_frame_rate','30/1')
    n,d=map(int,rate.split('/')); fps=n/d if d else 30
    duration=float(data.get('format',{}).get('duration') or video.get('duration',0))
    if not duration or not 0<fps<=240: raise HTTPException(422,'Video has no usable duration or frame rate.')
    return {'duration':duration,'fps':fps,'frame_rate':rate,'width':video['width'],'height':video['height'],'codec':video['codec_name'],'audio':any(s['codec_type']=='audio' for s in data['streams']),'streams':data['streams']}

def unpack_bundle(path, destination):
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>4*1024**3: raise HTTPException(422,'Character bundle is larger than the 4 GB import limit.')
        for item in z.infolist():
            target=safe(destination,item.filename)
            if item.external_attr>>16 & 0o170000 == 0o120000: raise HTTPException(422,'Character bundles cannot contain symbolic links.')
            if item.is_dir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as source, target.open('wb') as out: shutil.copyfileobj(source,out)
    matches=list(destination.rglob('manifest.json'))
    if len(matches)!=1: raise HTTPException(422,'Include exactly one manifest.json in the character ZIP.')
    manifest=json.loads(matches[0].read_text())
    if not isinstance(manifest,dict): raise HTTPException(422,'manifest.json must contain a JSON object.')
    required=['character_id','display_name','blend_file','scene','camera','viseme_map','minimum_blender_version','maximum_blender_version']
    missing=[x for x in required if not manifest.get(x)]
    if missing: raise HTTPException(422,'Manifest is missing: '+', '.join(missing))
    if not isinstance(manifest['viseme_map'],dict): raise HTTPException(422,'viseme_map must map cue labels to shape-key names.')
    for field in required:
        if field!='viseme_map' and not isinstance(manifest[field],str): raise HTTPException(422,field+' must be a string.')
    for cue in 'ABCDEFGHX':
        if not isinstance(manifest['viseme_map'].get(cue),str) or not manifest['viseme_map'][cue]: raise HTTPException(422,f'Missing mouth mapping for {cue}.')
    blend=safe(matches[0].parent,manifest['blend_file'])
    if not blend.is_file() or blend.suffix!='.blend': raise HTTPException(422,'Manifest must reference a bundled .blend file.')
    return manifest, matches[0], blend

def timeline_issues(p):
    issues=[]; spans=[]; video=next((a for a in reversed(p['assets']) if a['kind']=='video'),None)
    for s in p['segments']:
        if s.get('duration') is None: continue
        spans.append((s['start'],s['start']+s['duration'],s['id']))
    spans.sort()
    for i,(start,end,sid) in enumerate(spans):
        if video and end>video['probe']['duration']+0.01 and p['timeline']['duration_policy']=='require_fit': issues.append('Narration exceeds the video. Move it or choose Extend with a frozen last frame.')
        if i and start<max(x[1] for x in spans[:i])-0.001: issues.append('Narration segments overlap. Adjust their start times before export.')
    return list(dict.fromkeys(issues))


def model_config(cfg):
    try:
        path=Path(cfg['model_path'])
        data=json.loads((path/'config.json').read_text())
        expected={'CustomVoice':'custom_voice','VoiceDesign':'voice_design'}[cfg['variant']]
        if data.get('model_type')!='qwen3_tts' or data.get('tts_model_size')!='1b7' or data.get('tts_model_type')!=expected: return None
        if not list(path.glob('*.safetensors')): return None
        return data
    except (OSError,ValueError,KeyError): return None
