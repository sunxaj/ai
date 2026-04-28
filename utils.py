#!/usr/bin/env python3
import base64
import re
from flask import Flask, jsonify, request, send_from_directory, make_response, render_template
import psutil
import time
import os
import glob
import hashlib
from urllib.parse import urlparse
import subprocess

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

THUMBNAILS_FOLDER = os.path.join(os.path.dirname(__file__), 'thumbnails')
os.makedirs(THUMBNAILS_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder='.', static_url_path='', template_folder='.')
app.config['JSON_AS_ASCII'] = False

def bytes_to_gb(b):
    return round(b / (1024 ** 3), 2)

@app.route('/stats')
def stats():
    # Small delay to allow cpu_percent to sample
    cpu = psutil.cpu_percent(interval=0.25)
    cpu_count = psutil.cpu_count(logical=True)
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    res = {
        'timestamp': time.time(),
        'cpu_percent': cpu,
        'cpu_count': cpu_count,
        'memory_total_gb': bytes_to_gb(vm.total),
        'memory_available_gb': bytes_to_gb(vm.available),
        'memory_used_gb': bytes_to_gb(vm.used),
        'memory_percent': vm.percent,
        'swap_total_gb': bytes_to_gb(swap.total),
        'swap_used_gb': bytes_to_gb(swap.used),
        'platform': os.name
    }
    response = make_response(jsonify(res))
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


@app.route('/list-videos')
def list_videos():
    files = sorted(glob.glob('vd_h/*.mp4'))
    files = [f.replace('\\', '/') for f in files]
    response = make_response(jsonify(files))
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/list-images')
def list_images():
    # Return list of image paths from specified folder (default: prn)
    folder = request.args.get('folder', 'prn')
    print(f"list_images called with folder param: {folder}")
    # Only allow 'images' or 'prn' folders
    if folder not in ['images', 'prn']:
        folder = 'prn'
    
    patterns = [f'{folder}/*.png', f'{folder}/*.jpg', f'{folder}/*.jpeg', f'{folder}/*.webp']
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    # Keep deterministic order
    files = sorted(set(files))
    # Normalize paths for URLs
    files = [f.replace('\\','/') for f in files]
    print(f"Returning {len(files)} files from {folder}: {files[:3]}")
    response = make_response(jsonify(files))
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/list-output-images')
def list_output_images():
    # Return list of images from ../share/output folder
    output_folder = os.path.join(os.path.dirname(__file__), '..', 'share', 'output')
    output_folder = os.path.abspath(output_folder)
    
    if not os.path.exists(output_folder):
        return jsonify([])
    
    patterns = ['*.png', '*.jpg', '*.jpeg', '*.webp']
    files = []
    for pattern in patterns:
        files.extend(glob.glob(os.path.join(output_folder, pattern)))
    
    # Sort by modification time (newest first)
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # Create response with file info
    result = []
    for filepath in files:
        filename = os.path.basename(filepath)
        size_bytes = os.path.getsize(filepath)
        # Format size
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        
        result.append({
            'name': filename,
            'path': f'/share-output/{filename}',
            'size': size_str
        })
    
    response = make_response(jsonify(result))
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/share-output/<path:filename>')
def serve_output_image(filename):
    output_folder = os.path.join(os.path.dirname(__file__), '..', 'share', 'output')
    output_folder = os.path.abspath(output_folder)
    return send_from_directory(output_folder, filename)

@app.route('/delete-output-image', methods=['POST'])
def delete_output_image():
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'message': 'Invalid data'}), 400
    
    filename = data['filename']
    output_folder = os.path.join(os.path.dirname(__file__), '..', 'share', 'output')
    output_folder = os.path.abspath(output_folder)
    filepath = os.path.join(output_folder, filename)
    
    # Security check: ensure the file is within the output folder
    if not filepath.startswith(output_folder):
        return jsonify({'message': 'Invalid file path'}), 403
    
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'message': 'Image deleted successfully'}), 200
        else:
            return jsonify({'message': 'File not found'}), 404
    except Exception as e:
        return jsonify({'message': f'Error deleting file: {str(e)}'}), 500

@app.route('/get-image-metadata', methods=['POST'])
def get_image_metadata():
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'message': 'Invalid data'}), 400
    
    filename = data['filename']
    output_folder = os.path.join(os.path.dirname(__file__), '..', 'share', 'output')
    output_folder = os.path.abspath(output_folder)
    filepath = os.path.join(output_folder, filename)
    
    # Security check
    if not filepath.startswith(output_folder):
        return jsonify({'message': 'Invalid file path'}), 403
    
    try:
        if not os.path.exists(filepath):
            return jsonify({'message': 'File not found'}), 404
        
        # Extract PNG metadata
        metadata = {}
        text_inputs = []
        
        print(f"[DEBUG] Processing file: {filename}")
        
        if filepath.lower().endswith('.png'):
            try:
                from PIL import Image
                import json as json_lib
                import re
                img = Image.open(filepath)
                
                print(f"[DEBUG] Image opened successfully")
                
                # ComfyUI stores metadata in PNG info chunks
                if hasattr(img, 'info'):
                    print(f"[DEBUG] Image has info attribute, keys: {list(img.info.keys())}")
                    # Get raw prompt string
                    if 'prompt' in img.info:
                        print(f"[DEBUG] prompt found in image metadata")
                        try:
                            prompt_str = img.info['prompt']
                            print(f"[DEBUG] prompt string length: {len(prompt_str)}")
                            print(f"[DEBUG] prompt preview (first 3000 chars): {prompt_str[:3000]}")
                            
                            # Parse full prompt to get node titles
                            prompt = json_lib.loads(prompt_str)
                            print(f"[DEBUG] prompt parsed, has {len(prompt_str)} nodes")
                            
                            matched_count = 0
                            for node_id, node in prompt.items():
                                print(f"[DEBUG] Checking node {node_id}: type={type(node)}, has_inputs={'inputs' in node if isinstance(node, dict) else False}")
                                if isinstance(node, dict) and 'inputs' in node:
                                    inputs = node['inputs']
                                    print(f"[DEBUG] Node {node_id} inputs keys: {list(inputs.keys()) if isinstance(inputs, dict) else 'not a dict'}")
                                    if isinstance(inputs, dict) and 'text' in inputs:
                                            text_value = inputs['text']
                                            if isinstance(text_value, str) and text_value.strip():
                                                node_title = ''
                                                if '_meta' in node and 'title' in node['_meta']:
                                                    node_title = node['_meta']['title']
                                                elif 'class_type' in node:
                                                    node_title = node['class_type']
                                                else:
                                                    node_title = f'Node {node_id}'
                                                
                                                print(f"[DEBUG] Matched text block #{matched_count + 1}: Node={node_title}, Length={len(text_value)} chars")
                                                print(f"[DEBUG] Preview: {text_value[:100]}...")
                                                
                                                if 'prompt' in node_title.lower():
                                                    text_inputs.append({
                                                    'node_title': node_title,
                                                    'text': text_value
                                                })
                                                text_inputs.sort(key=lambda x: x['node_title'], reverse=True)
                                                
                                                matched_count += 1
                                                # Only extract first 3 text blocks
                                                if matched_count >= 3:
                                                    print(f"[DEBUG] Stopping at 3 text blocks")
                                                    break
                                
                                print(f"[DEBUG] Total extracted: {len(text_inputs)} text blocks")
                        except Exception as e:
                            print(f"[ERROR] Error parsing workflow: {e}")
                    
                    #Fallback to prompt if no text inputs found
                    if not text_inputs and 'prompt' in img.info:
                       text_inputs.append({
                           'node_title': 'Prompt',
                            'text': img.info['prompt']
                       })
                
                img.close()
            except Exception as e:
                print(f"[ERROR] Error reading PNG metadata: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"[DEBUG] Returning {len(text_inputs)} text inputs")
        return jsonify({'text_inputs': text_inputs}), 200
    except Exception as e:
        return jsonify({'message': f'Error reading metadata: {str(e)}'}), 500

@app.route('/image-cropper')
def image_cropper():
    return render_template('cropper.html')

@app.route('/save', methods=['POST'])
def save_cropped_image():
    data = request.get_json()
    if not data or 'image' not in data or 'filename' not in data:
        return jsonify({'message': 'Invalid data'}), 400

    try:
        image_data = data['image']
        original_filename = data['filename']
        
        # Decode the base64 string
        format, imgstr = image_data.split(';base64,') 
        ext = format.split('/')[-1] 
        image_bytes = base64.b64decode(imgstr)

        # Create ~/Downloads/cropped folder if it doesn't exist
        downloads_path = os.path.expanduser('~/Downloads/cropped')
        os.makedirs(downloads_path, exist_ok=True)

        # Use the same filename (overwrite silently if exists)
        filename = original_filename
        filepath = os.path.join(downloads_path, filename)

        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        return jsonify({'message': f'Image saved to ~/Downloads/cropped/{filename}'}), 200
    except Exception as e:
        return jsonify({'message': f'Error saving image: {str(e)}'}), 500

@app.route('/save-bookmarks', methods=['POST'])
def save_bookmarks():
    data = request.get_json()
    if not data or 'html' not in data:
        return jsonify({'message': 'Invalid data'}), 400
    
    try:
        filepath = os.path.join(os.path.dirname(__file__), 'my_bookmarks.html')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data['html'])
        return jsonify({'message': 'Bookmarks saved successfully'}), 200
    except Exception as e:
        return jsonify({'message': f'Error saving bookmarks: {str(e)}'}), 500

@app.route('/load-bookmarks')
def load_bookmarks():
    try:
        filepath = os.path.join(os.path.dirname(__file__), 'my_bookmarks.html')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        else:
            return '', 204
    except Exception as e:
        return jsonify({'message': f'Error loading bookmarks: {str(e)}'}), 500

@app.route('/generate-thumbnail', methods=['POST'])
def generate_thumbnail():
    data = request.get_json()
    if not data or 'url' not in data or 'id' not in data:
        return jsonify({'message': 'Invalid data'}), 400
    
    url = data['url']
    bookmark_id = data['id']
    
    # Generate filename from bookmark ID
    filename = f"{bookmark_id}.png"
    filepath = os.path.join(THUMBNAILS_FOLDER, filename)
    
    # Check if thumbnail already exists
    if os.path.exists(filepath):
        print(f"Thumbnail already exists for {url} at {filepath}")
        return jsonify({'exists': True, 'path': f'/thumbnails/{filename}'}), 200

    
    try:
        # Use playwright to take screenshot
        # First check if playwright is available
        try:
            print("Checking for Playwright availability...")
            result = subprocess.run(
                ['python3', '-c', 'from playwright.sync_api import sync_playwright'],
                capture_output=True,
                timeout=5
            )
            playwright_available = result.returncode == 0
        except:
            playwright_available = False
        
        if playwright_available:
            # Use playwright to capture screenshot
            screenshot_script = f'''
from playwright.sync_api import sync_playwright
import sys

url = "{url}"
filepath = "{filepath}"

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={{"width": 640, "height": 400}})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.screenshot(path=filepath, full_page=False)
        browser.close()
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {{e}}")
    sys.exit(1)
'''
            result = subprocess.run(
                ['python3', '-c', screenshot_script],
                capture_output=True,
                timeout=40,
                text=True
            )
            
            if result.returncode == 0 and os.path.exists(filepath):
                print(f"Thumbnail generated for {url} at {filepath}")
                return jsonify({'exists': False, 'path': f'/thumbnails/{filename}', 'success': True}), 200
            else:
                print(f"Failed to generate thumbnail for {url}: {result.stderr}")
                return jsonify({'message': 'Failed to generate thumbnail', 'error': result.stderr}), 500
        else:
            # Playwright not available, create placeholder
            return jsonify({'message': 'Playwright not installed', 'exists': False}), 400
            
    except subprocess.TimeoutExpired:
        return jsonify({'message': 'Thumbnail generation timeout'}), 500
    except Exception as e:
        return jsonify({'message': f'Error generating thumbnail: {str(e)}'}), 500

@app.route('/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    filepath = os.path.join(THUMBNAILS_FOLDER, filename)
    if os.path.exists(filepath):
        return send_from_directory(THUMBNAILS_FOLDER, filename)
    else:
        # Return 404 but don't log it as an error
        return '', 404

@app.route('/', defaults={'path': 'slide.html'})
@app.route('/<path:path>')
def static_proxy(path):
    # Serve static files from repo root
    return send_from_directory('.', path)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Tiny system stats server (serves static files + /stats)')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default=5000, type=int)
    args = parser.parse_args()
    print(f'Serving on http://{args.host}:{args.port} - /stats available')
    app.run(host=args.host, port=args.port)
