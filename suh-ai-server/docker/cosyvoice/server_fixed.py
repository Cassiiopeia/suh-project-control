"""
CosyVoice fastapi 서빙 (패치판)
업스트림 server.py는 업로드 음성을 텐서로 변환해 frontend에 넘기지만,
현행 frontend는 load_wav(경로)를 기대해 TypeError로 죽는다.
→ 업로드를 임시 파일로 저장해 '경로'를 그대로 전달한다.
"""
import argparse
import os
import sys
import tempfile

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import StreamingResponse

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(f'{ROOT_DIR}/../../..')
sys.path.append(f'{ROOT_DIR}/../../../third_party/Matcha-TTS')

app = FastAPI()
cosyvoice = None


def generate_data(model_output):
    """합성 결과를 int16 mono raw PCM 스트림으로 변환 (업스트림과 동일 포맷)"""
    for i in model_output:
        yield (i['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()


def save_upload(upload: UploadFile) -> str:
    """frontend가 파일 경로를 기대하므로 업로드를 임시 WAV 파일로 저장"""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        f.write(upload.file.read())
        return f.name


def cleanup_stream(gen, path):
    """스트림 종료 후 임시 파일 제거"""
    try:
        yield from gen
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.post('/inference_zero_shot')
async def inference_zero_shot(tts_text: str = Form(), prompt_text: str = Form(),
                              prompt_wav: UploadFile = File()):
    path = save_upload(prompt_wav)
    output = cosyvoice.inference_zero_shot(tts_text, prompt_text, path)
    return StreamingResponse(cleanup_stream(generate_data(output), path))


@app.post('/inference_cross_lingual')
async def inference_cross_lingual(tts_text: str = Form(),
                                  prompt_wav: UploadFile = File()):
    path = save_upload(prompt_wav)
    output = cosyvoice.inference_cross_lingual(tts_text, path)
    return StreamingResponse(cleanup_stream(generate_data(output), path))


@app.post('/inference_instruct2')
async def inference_instruct2(tts_text: str = Form(), instruct_text: str = Form(),
                              prompt_wav: UploadFile = File()):
    path = save_upload(prompt_wav)
    output = cosyvoice.inference_instruct2(tts_text, instruct_text, path)
    return StreamingResponse(cleanup_stream(generate_data(output), path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50000)
    parser.add_argument('--model_dir', type=str, default='iic/CosyVoice2-0.5B')
    args = parser.parse_args()

    # AutoModel은 최신 레포 기준 — 구버전 호환을 위해 CosyVoice2 폴백
    try:
        from cosyvoice.cli.cosyvoice import AutoModel
        cosyvoice = AutoModel(model_dir=args.model_dir)
    except ImportError:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        cosyvoice = CosyVoice2(args.model_dir)

    uvicorn.run(app, host='0.0.0.0', port=args.port)
