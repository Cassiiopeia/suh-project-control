"""
Qwen3-TTS 0.6B CustomVoice 서빙 — 프리셋 화자(Sohee 등) 합성 FastAPI
"""
import io
import os
import re

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from qwen_tts import Qwen3TTSModel

MODEL_ID = os.environ.get('MODEL_ID', 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice')

app = FastAPI()
model = None


@app.on_event('startup')
def load_model():
    global model
    # bf16 — RTX 4060 지원, VRAM 절약. flash-attn은 빌드 부담이 커서 기본 어텐션 사용
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID, device_map='cuda:0', dtype=torch.bfloat16)


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = 'Sohee'
    language: str = 'Korean'


@app.get('/health')
def health():
    return {'ok': model is not None}


@app.post('/synthesize')
def synthesize(req: SynthesizeRequest):
    wavs, sr = model.generate_custom_voice(
        text=req.text, language=req.language, speaker=req.voice)
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format='WAV')
    return Response(buf.getvalue(), media_type='audio/wav')


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=7801)
