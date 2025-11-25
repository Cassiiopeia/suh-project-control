"""
OCR router
"""
from flask import Blueprint, request, jsonify
from service.ocr_service import OCRService
from model.ocr_model import (
    OcrUrlRequest,
    OcrUrlResponse,
    OcrBase64Request,
    OcrBase64Response,
    OcrUploadRequest,
    OcrUploadResponse,
    OcrRequest,
    OcrResponse
)
from config.app_config import DEFAULT_PROMPT, DEFAULT_MODEL
import logging

logger = logging.getLogger(__name__)

ocr_bp = Blueprint('ocr', __name__)
ocr_service = OCRService()


@ocr_bp.route('/ocr/url', methods=['POST'])
def ocr_url():
    """
    OCR endpoint for image URL
    
    Request Body:
    {
        "image_url": "https://...",
        "prompt": "Extract all text",   # Optional
        "model": "deepseek-ocr"        # Optional
    }
    
    Response:
    {
        "success": true,
        "result": "extracted text",
        "model": "deepseek-ocr",
        "prompt": "..."
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        
        # Create request model
        req = OcrUrlRequest(
            image_url=data.get('image_url', ''),
            prompt=data.get('prompt', DEFAULT_PROMPT),
            model=data.get('model', DEFAULT_MODEL)
        )
        
        # Process image from URL (validation and conversion handled in service)
        base64_image = ocr_service.process_image_url(req.image_url)
        
        # Perform OCR
        result = ocr_service.perform_ocr(base64_image, req.prompt, req.model)
        
        logger.info(f"OCR completed successfully (model={req.model})")
        
        # Create response model
        response = OcrUrlResponse(
            success=True,
            result=result,
            model=req.model,
            prompt=req.prompt
        )
        
        return jsonify({
            'success': response.success,
            'result': response.result,
            'model': response.model,
            'prompt': response.prompt
        }), 200
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        return jsonify({'error': str(e)}), 404
        
    except Exception as e:
        logger.error(f"OCR error: {str(e)}")
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


@ocr_bp.route('/ocr/base64', methods=['POST'])
def ocr_base64():
    """
    OCR endpoint for base64 encoded image
    
    Request Body:
    {
        "image_base64": "base64string",
        "prompt": "Extract all text",   # Optional
        "model": "deepseek-ocr"        # Optional
    }
    
    Response:
    {
        "success": true,
        "result": "extracted text",
        "model": "deepseek-ocr",
        "prompt": "..."
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        
        # Create request model
        req = OcrBase64Request(
            image_base64=data.get('image_base64', ''),
            prompt=data.get('prompt', DEFAULT_PROMPT),
            model=data.get('model', DEFAULT_MODEL)
        )
        
        # Process base64 image (validation and cleaning handled in service)
        base64_image = ocr_service.process_base64_image(req.image_base64)
        
        # Perform OCR
        result = ocr_service.perform_ocr(base64_image, req.prompt, req.model)
        
        logger.info(f"OCR completed successfully (model={req.model})")
        
        # Create response model
        response = OcrBase64Response(
            success=True,
            result=result,
            model=req.model,
            prompt=req.prompt
        )
        
        return jsonify({
            'success': response.success,
            'result': response.result,
            'model': response.model,
            'prompt': response.prompt
        }), 200
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
        
    except Exception as e:
        logger.error(f"OCR error: {str(e)}")
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


@ocr_bp.route('/ocr/upload', methods=['POST'])
def ocr_upload():
    """
    OCR endpoint for uploaded image file (multipart/form-data)
    
    Form Data:
    - file: Image file (required)
    - prompt: OCR prompt (optional)
    - model: Ollama model name (optional)
    
    Response:
    {
        "success": true,
        "result": "extracted text",
        "model": "deepseek-ocr",
        "prompt": "..."
    }
    """
    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Extract parameters from form data
        prompt = request.form.get('prompt', DEFAULT_PROMPT)
        model = request.form.get('model', DEFAULT_MODEL)
        
        # Process uploaded file
        logger.info(f"Processing uploaded file: {file.filename}")
        base64_image = ocr_service.get_image_base64_from_file(file)
        
        # Perform OCR
        result = ocr_service.perform_ocr(base64_image, prompt, model)
        
        logger.info(f"OCR completed successfully (model={model})")
        
        # Create response model
        response = OcrUploadResponse(
            success=True,
            result=result,
            model=model,
            prompt=prompt
        )
        
        return jsonify({
            'success': response.success,
            'result': response.result,
            'model': response.model,
            'prompt': response.prompt
        }), 200
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
        
    except Exception as e:
        logger.error(f"OCR error: {str(e)}")
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


@ocr_bp.route('/ocr', methods=['POST'])
def ocr():
    """
    OCR endpoint

    Request Body:
    {
        "image_url": "https://...",     # OR
        "image_base64": "base64string",
        "prompt": "Extract all text",   # Optional
        "model": "deepseek-ocr"        # Optional
    }

    Response:
    {
        "success": true,
        "result": "extracted text",
        "model": "deepseek-ocr",
        "prompt": "..."
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        # Create request model
        req = OcrRequest(
            image_url=data.get('image_url', ''),
            image_base64=data.get('image_base64', ''),
            prompt=data.get('prompt', DEFAULT_PROMPT),
            model=data.get('model', DEFAULT_MODEL)
        )

        # Process image source
        # Priority: image_base64 (if non-empty) > image_url
        base64_image = None
        
        if req.image_base64 and isinstance(req.image_base64, str) and req.image_base64.strip():
            # Process base64 image (validation handled in service)
            base64_image = ocr_service.process_base64_image(req.image_base64)
        elif req.image_url and isinstance(req.image_url, str) and req.image_url.strip():
            # Process image URL (validation handled in service)
            base64_image = ocr_service.process_image_url(req.image_url)
        else:
            return jsonify({
                'error': 'Either image_url or image_base64 required (non-empty)'
            }), 400

        # Perform OCR
        result = ocr_service.perform_ocr(base64_image, req.prompt, req.model)

        logger.info(f"OCR completed successfully (model={req.model})")

        # Create response model
        response = OcrResponse(
            success=True,
            result=result,
            model=req.model,
            prompt=req.prompt
        )

        return jsonify({
            'success': response.success,
            'result': response.result,
            'model': response.model,
            'prompt': response.prompt
        }), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400

    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        return jsonify({'error': str(e)}), 404

    except Exception as e:
        logger.error(f"OCR error: {str(e)}")
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500

