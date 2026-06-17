"""
Vision router
"""
from flask import Blueprint, request, jsonify
from service.vision_service import VisionService
from model.vision_model import (
    VisionUrlRequest,
    VisionUrlResponse,
    VisionBase64Request,
    VisionBase64Response,
    VisionUploadRequest,
    VisionUploadResponse,
    VisionRequest,
    VisionResponse
)
from config.app_config import DEFAULT_VISION_PROMPT, DEFAULT_VISION_MODEL
import logging

logger = logging.getLogger(__name__)

vision_bp = Blueprint('vision', __name__)
vision_service = VisionService()


@vision_bp.route('/vision/url', methods=['POST'])
def vision_url():
    """
    Vision endpoint for image URL

    Request Body:
    {
        "image_url": "https://...",
        "prompt": "이 이미지를 설명해줘",  # Optional
        "model": "gemma3:4b"              # Optional
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        req = VisionUrlRequest(
            image_url=data.get('image_url', ''),
            prompt=data.get('prompt', DEFAULT_VISION_PROMPT),
            model=data.get('model', DEFAULT_VISION_MODEL)
        )

        base64_image = vision_service.process_image_url(req.image_url)
        result = vision_service.describe_image(base64_image, req.prompt, req.model)

        logger.info(f"Vision completed successfully (model={req.model})")
        response = VisionUrlResponse(success=True, result=result, model=req.model, prompt=req.prompt)
        return jsonify({'success': response.success, 'result': response.result, 'model': response.model, 'prompt': response.prompt}), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Vision error: {str(e)}")
        return jsonify({'error': f'Vision failed: {str(e)}'}), 500


@vision_bp.route('/vision/base64', methods=['POST'])
def vision_base64():
    """
    Vision endpoint for base64 encoded image

    Request Body:
    {
        "image_base64": "base64string",
        "prompt": "이 이미지를 설명해줘",  # Optional
        "model": "gemma3:4b"              # Optional
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        req = VisionBase64Request(
            image_base64=data.get('image_base64', ''),
            prompt=data.get('prompt', DEFAULT_VISION_PROMPT),
            model=data.get('model', DEFAULT_VISION_MODEL)
        )

        base64_image = vision_service.process_base64_image(req.image_base64)
        result = vision_service.describe_image(base64_image, req.prompt, req.model)

        logger.info(f"Vision completed successfully (model={req.model})")
        response = VisionBase64Response(success=True, result=result, model=req.model, prompt=req.prompt)
        return jsonify({'success': response.success, 'result': response.result, 'model': response.model, 'prompt': response.prompt}), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Vision error: {str(e)}")
        return jsonify({'error': f'Vision failed: {str(e)}'}), 500


@vision_bp.route('/vision/upload', methods=['POST'])
def vision_upload():
    """
    Vision endpoint for uploaded image file (multipart/form-data)

    Form Data:
    - file: Image file (required)
    - prompt: Description prompt (optional)
    - model: Ollama model name (optional)
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        prompt = request.form.get('prompt', DEFAULT_VISION_PROMPT)
        model = request.form.get('model', DEFAULT_VISION_MODEL)

        logger.info(f"Processing uploaded file: {file.filename}")
        base64_image = vision_service.get_image_base64_from_file(file)
        result = vision_service.describe_image(base64_image, prompt, model)

        logger.info(f"Vision completed successfully (model={model})")
        response = VisionUploadResponse(success=True, result=result, model=model, prompt=prompt)
        return jsonify({'success': response.success, 'result': response.result, 'model': response.model, 'prompt': response.prompt}), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Vision error: {str(e)}")
        return jsonify({'error': f'Vision failed: {str(e)}'}), 500


@vision_bp.route('/vision', methods=['POST'])
def vision():
    """
    Vision unified endpoint

    Request Body:
    {
        "image_url": "https://...",       # OR
        "image_base64": "base64string",
        "prompt": "이 이미지를 설명해줘",  # Optional
        "model": "gemma3:4b"              # Optional
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        req = VisionRequest(
            image_url=data.get('image_url', ''),
            image_base64=data.get('image_base64', ''),
            prompt=data.get('prompt', DEFAULT_VISION_PROMPT),
            model=data.get('model', DEFAULT_VISION_MODEL)
        )

        base64_image = None
        if req.image_base64 and isinstance(req.image_base64, str) and req.image_base64.strip():
            base64_image = vision_service.process_base64_image(req.image_base64)
        elif req.image_url and isinstance(req.image_url, str) and req.image_url.strip():
            base64_image = vision_service.process_image_url(req.image_url)
        else:
            return jsonify({'error': 'Either image_url or image_base64 required (non-empty)'}), 400

        result = vision_service.describe_image(base64_image, req.prompt, req.model)

        logger.info(f"Vision completed successfully (model={req.model})")
        response = VisionResponse(success=True, result=result, model=req.model, prompt=req.prompt)
        return jsonify({'success': response.success, 'result': response.result, 'model': response.model, 'prompt': response.prompt}), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Vision error: {str(e)}")
        return jsonify({'error': f'Vision failed: {str(e)}'}), 500
