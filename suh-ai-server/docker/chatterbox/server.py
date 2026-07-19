"""
Chatterbox Multilingual 서빙 — 기본 보이스 + 선택적 레퍼런스(원샷 클로닝) FastAPI
"""
import io
import os
import tempfile

import torchaudio
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import Response
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

app = FastAPI()
model = None


@app.on_event('startup')
def load_model():
    global model
    model = ChatterboxMultilingualTTS.from_pretrained(device='cuda')


@app.get('/health')
def health():
    return {'ok': model is not None}


@app.post('/synthesize')
async def synthesize(text: str = Form(), lang: str = Form('ko'),
                     prompt_wav: UploadFile = File(None)):
    kwargs = {}
    tmp_path = None
    try:
        if prompt_wav is not None:
            # 레퍼런스가 오면 그 목소리로 클로닝 — 없으면 내장 기본 보이스
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                f.write(await prompt_wav.read())
                tmp_path = f.name
            kwargs['audio_prompt_path'] = tmp_path
        wav = model.generate(text, language_id=lang, **kwargs)
        buf = io.BytesIO()
        torchaudio.save(buf, wav, model.sr, format='wav')
        return Response(buf.getvalue(), media_type='audio/wav')
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=7802)
