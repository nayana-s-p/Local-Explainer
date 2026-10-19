"""Isolated, strictly offline Qwen3-TTS worker. Input/output via managed JSON files."""
import json, os, sys, time
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel
request=json.load(open(sys.argv[1]))
config=json.load(open(os.path.join(request['model_path'],'config.json')))
if config.get('tts_model_size')!='1b7': raise RuntimeError('The selected model must be Qwen3-TTS 1.7B.')
device=request['device']
if device=='mps' and not torch.backends.mps.is_available(): raise RuntimeError('MPS is unavailable; select CPU explicitly in Setup.')
print('EXPLAINER_STAGE load_model',flush=True)
model=Qwen3TTSModel.from_pretrained(request['model_path'],device_map=device,dtype=torch.float32 if device=='cpu' else torch.float16,attn_implementation='eager',local_files_only=True)
print('EXPLAINER_STAGE generate_audio',flush=True)
voice=request['voice']
if voice['language'].lower() not in [x.lower() for x in model.get_supported_languages()]: raise RuntimeError('The installed model does not support this language.')
if voice['variant']=='CustomVoice':
    if voice['speaker'].lower() not in [x.lower() for x in model.get_supported_speakers()]: raise RuntimeError('The installed model does not support this speaker.')
    wavs,sr=model.generate_custom_voice(text=request['text'],language=voice['language'],speaker=voice['speaker'],instruct=voice.get('instruct',''),max_new_tokens=8192)
elif voice['variant']=='VoiceDesign':
    wavs,sr=model.generate_voice_design(text=request['text'],language=voice['language'],instruct=voice['instruct'],max_new_tokens=8192)
else: raise RuntimeError('Choose CustomVoice or VoiceDesign. Base voice cloning is outside this build.')
if len(wavs[0])/sr>=670 or len(wavs[0])==0: raise RuntimeError('Generation reached a limit or produced empty audio. Split the narration into shorter segments; output was not marked complete.')
import importlib.metadata
with open(request['output']+'.metadata.json','w') as report:
    json.dump({'qwen_tts':importlib.metadata.version('qwen-tts'),'torch':torch.__version__,'languages':model.get_supported_languages(),'sample_rate':sr},report)
sf.write(request['output'],wavs[0],sr,subtype='PCM_16')
print(json.dumps({'sample_rate':sr,'duration':len(wavs[0])/sr,'languages':model.get_supported_languages()}),flush=True)
