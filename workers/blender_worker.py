"""Run inside Blender. Never enable automatic execution of bundle scripts."""
import bpy, json, sys, math
from pathlib import Path
req=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
def main():
    m=req['manifest']; scene=bpy.data.scenes.get(m['scene'])
    if not scene: raise RuntimeError('Scene is missing: '+m['scene'])
    camera=bpy.data.objects.get(m['camera'])
    if not camera or camera.type!='CAMERA': raise RuntimeError('Camera is missing: '+m['camera'])
    scene.camera=camera
    version='.'.join(map(str,bpy.app.version))
    def version_tuple(s): return tuple(int(x) for x in s.split('.')[:3])
    if not version_tuple(m['minimum_blender_version'])<=bpy.app.version<=version_tuple(m['maximum_blender_version']): raise RuntimeError('Blender version is outside the manifest tested range: '+version)
    keys={}
    for obj in scene.objects:
        if obj.type=='MESH' and obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:
                keys.setdefault(key.name,[]).append(key)
    missing=[name for name in m['viseme_map'].values() if name not in keys]
    if missing: raise RuntimeError('Missing shape keys: '+', '.join(missing))
    if req['mode']=='validate':
        Path(req['report']).write_text(json.dumps({'valid':True,'blender_version':version,'camera':camera.name,'scene':scene.name,'shape_keys':list(keys),'view_layers':[l.name for l in scene.view_layers]}))
    else:
        bpy.context.window.scene=scene
        scene.render.film_transparent=True
        scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGBA'
        scene.render.resolution_x=req['width']; scene.render.resolution_y=req['height']; scene.render.resolution_percentage=100
        scene.render.fps=round(req['fps']); scene.render.fps_base=round(req['fps'])/req['fps']
        fps=req['fps']; duration=req['duration']
        scene.frame_start=1; scene.frame_end=math.ceil(duration*fps)
        idle=m.get('idle_action'); rig=bpy.data.objects.get(m.get('rig_object',''))
        if idle:
            action=bpy.data.actions.get(idle)
            if not action or not rig: raise RuntimeError('Idle action or rig_object is missing.')
            rig.animation_data_create(); rig.animation_data.action=action
        for mapped in set(m['viseme_map'].values()):
            for key in keys[mapped]: key.value=0
        for segment in req['segments']:
            cues=json.loads(Path(segment['cue_path']).read_text())['mouthCues']
            for cue in cues:
                pose=m['viseme_map'][cue['value']]
                begin=1+round((segment['start']+cue['start'])*fps)
                end=max(begin+1,1+round((segment['start']+cue['end'])*fps))
                for mapped in set(m['viseme_map'].values()):
                    for key in keys[mapped]:
                        key.value=0; key.keyframe_insert('value',frame=max(1,begin-1))
                        key.value=1 if mapped==pose else 0; key.keyframe_insert('value',frame=begin)
                        key.keyframe_insert('value',frame=end-1)
                        key.value=0; key.keyframe_insert('value',frame=end)
        # Use constant interpolation to preserve the discrete Rhubarb mouth poses.
        for obj in scene.objects:
            if obj.type=='MESH' and obj.data.shape_keys:
                ad=obj.data.shape_keys.animation_data
                if ad and ad.action:
                    try:
                        for fc in ad.action.fcurves:
                            for point in fc.keyframe_points: point.interpolation='CONSTANT'
                    except AttributeError: pass
        output=Path(req['output']); output.mkdir(parents=True,exist_ok=True)
        for frame in range(1,scene.frame_end+1):
            target=output/f'{frame:06d}.png'
            if target.exists():
                try:
                    image=bpy.data.images.load(str(target),check_existing=False)
                    valid=tuple(image.size)==(req['width'],req['height'])
                    bpy.data.images.remove(image)
                    if valid: continue
                except RuntimeError: pass
                target.unlink(missing_ok=True)
            scene.frame_set(frame); scene.render.filepath=str(target)
            bpy.ops.render.render(write_still=True)
            print('EXPLAINER_PROGRESS '+str(frame/scene.frame_end),flush=True)
        Path(req['report']).write_text(json.dumps({'frames':scene.frame_end,'blender_version':version,'fps':fps,'width':req['width'],'height':req['height']}))

try:
    main()
except Exception as e:
    Path(req["report"]).write_text(json.dumps({"error":str(e)}))
    raise
