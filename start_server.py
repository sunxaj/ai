#!/usr/bin/env python3
import base64
import re
from flask import Flask, jsonify, request, send_from_directory, make_response, render_template
import psutil
import time
import os
import glob

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder='.', static_url_path='', template_folder='.')

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

@app.route('/image-cropper')
def image_cropper():
    return render_template('image_cropper.html')

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
