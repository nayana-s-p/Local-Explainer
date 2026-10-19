"""Create a deliberately simple, compatible sample rig in Blender."""
import bpy, json, math
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
def mat(name,color):
 m=bpy.data.materials.new(name);m.diffuse_color=color;m.use_nodes=True
 bsdf=m.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=color;bsdf.inputs['Roughness'].default_value=.7
 return m
skin=mat('Warm cream',(0.88,.76,.55,1)); green=mat('Sage sweater',(.18,.4,.29,1)); dark=mat('Eyes and mouth',(.04,.065,.055,1)); pink=mat('Blush',(.85,.40,.32,1))
def sphere(name,loc,scale,material):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,location=loc)
 obj=bpy.context.object;obj.name=name;obj.scale=scale;obj.data.materials.append(material)
 for poly in obj.data.polygons:poly.use_smooth=True
 return obj
sphere('Body',(0,0,.65),(.62,.40,.67),green)
sphere('Head',(0,0,1.48),(.47,.37,.48),skin)
for x in [-.19,.19]:
 sphere('Eye',(x,-.342,1.56),(.045,.026,.065),dark)
 sphere('Cheek',(x*1.3,-.30,1.4),(.075,.022,.04),pink)
sphere('Nose',(0,-.37,1.47),(.047,.035,.05),skin)
# A front-facing mouth disk whose per-label shape keys change its contour.
verts=[(0,-.372,1.33)]+[(.09*math.cos(i*2*math.pi/24),-.372,1.33+.016*math.sin(i*2*math.pi/24)) for i in range(24)]
faces=[(0,i+1,(i+1)%24+1) for i in range(24)]
mesh=bpy.data.meshes.new('MouthGeometry');mesh.from_pydata(verts,[],faces);mesh.update()
mouth=bpy.data.objects.new('Mouth',mesh);bpy.context.collection.objects.link(mouth);mouth.data.materials.append(dark)
mouth.shape_key_add(name='Basis')
shapes={'A':(.12,.012),'B':(.11,.035),'C':(.09,.08),'D':(.09,.115),'E':(.065,.065),'F':(.045,.09),'G':(.12,.025),'H':(.095,.035),'X':(.085,.012)}
for label,(width,height) in shapes.items():
 key=mouth.shape_key_add(name='viseme_'+label)
 for i in range(24):
  key.data[i+1].co=(width*math.cos(i*2*math.pi/24),-.375,1.33+height*math.sin(i*2*math.pi/24))
# Gentle idle sway on a parent empty, matching manifest idle_action/rig_object.
rig=bpy.data.objects.new('PresenterRig',None);bpy.context.collection.objects.link(rig)
for obj in list(bpy.context.scene.objects):
 if obj.type=='MESH':obj.parent=rig
for frame,angle in [(1,-.012),(36,.012),(72,-.012)]:
 rig.rotation_euler[1]=angle;rig.keyframe_insert(data_path='rotation_euler',frame=frame)
rig.animation_data.action.name='GentleIdle'
bpy.ops.object.camera_add(location=(0,-6,1.3));camera=bpy.context.object;camera.name='PresenterCamera';camera.rotation_euler=(Vector((0,0,1.08))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=2.5
bpy.ops.object.light_add(type='AREA',location=(-3,-4,5));bpy.context.object.data.energy=450;bpy.context.object.data.size=5
bpy.ops.object.light_add(type='AREA',location=(3,-2,3));bpy.context.object.data.energy=200;bpy.context.object.data.size=4
scene=bpy.context.scene;scene.name='PresenterScene';scene.camera=camera;scene.render.engine='BLENDER_EEVEE';scene.render.film_transparent=True;scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.fps=24
bpy.ops.wm.save_as_mainfile(filepath=str(root/'presenter.blend'))
manifest={'character_id':'sage-presenter','display_name':'Sage · Sample presenter','blend_file':'presenter.blend','minimum_blender_version':'5.2.2','maximum_blender_version':'5.2.2','scene':'PresenterScene','camera':'PresenterCamera','frame_rate':24,'transparent_background':True,'viseme_map':{c:'viseme_'+c for c in 'ABCDEFGHX'},'idle_action':'GentleIdle','rig_object':'PresenterRig','anchor':'bottom-center','safe_overlay_bounds':[0,0,1,1],'render_presets':['square-alpha'],'required_fonts':[],'required_textures':[]}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Created sample character bundle')
