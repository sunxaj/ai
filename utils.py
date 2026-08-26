#!/usr/bin/env python3
import base64
import hashlib
import re
import json
import subprocess
from urllib.parse import quote
from flask import Flask, jsonify, request, send_from_directory, make_response, render_template
import psutil
import time
import os
import glob

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

VIDEOS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'videos')
os.makedirs(VIDEOS_FOLDER, exist_ok=True)

THUMBNAILS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thumbnails')
os.makedirs(THUMBNAILS_FOLDER, exist_ok=True)

def resolve_video_folder(folder_param):
    if not folder_param:
        return VIDEOS_FOLDER
    folder = os.path.abspath(folder_param)
    if not os.path.isdir(folder):
        return None
    return folder

def thumbnail_path_for(folder, name):
    key = hashlib.sha256(f"{folder}|{name}".encode()).hexdigest()[:16]
    return os.path.join(THUMBNAILS_FOLDER, f"{key}.jpg")

def ensure_thumbnail(folder, name):
    fp = os.path.join(folder, name)
    if not os.path.isfile(fp):
        return None
    tp = thumbnail_path_for(folder, name)
    try:
        if os.path.exists(tp) and os.path.getmtime(tp) >= os.path.getmtime(fp):
            return tp
        result = subprocess.run(
            ['ffmpeg', '-y', '-sseof', '-0.5', '-i', fp,
             '-frames:v', '1', '-q:v', '3', tp],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not os.path.exists(tp):
            return None
        return tp
    except Exception:
        if os.path.exists(tp):
            try:
                os.remove(tp)
            except OSError:
                pass
        return None

def remove_thumbnail(folder, name):
    tp = thumbnail_path_for(folder, name)
    if os.path.exists(tp):
        try:
            os.remove(tp)
        except OSError:
            pass

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
    files = sorted(glob.glob('videos/*.mp4'))
    files = [f.replace('\\', '/') for f in files]
    files.sort(key=lambda x: os.stat(x).st_birthtime, reverse=True)
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

@app.route('/api/videos')
def api_list_videos():
    folder = resolve_video_folder(request.args.get('folder', ''))
    if not folder:
        return jsonify({'error': 'invalid folder'}), 400
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(1, int(request.args.get('per_page', 20))))
    files = sorted(glob.glob(os.path.join(folder, '*.mp4')))
    total = len(files)
    start = (page - 1) * per_page
    page_files = files[start:start + per_page]
    result = []
    for fp in page_files:
        name = os.path.basename(fp)
        folder_q = quote(folder, safe='')
        name_q = quote(name, safe='')
        result.append({
            'name': name,
            'path': f'/api/video-file?folder={folder_q}&name={name_q}',
            'thumbnail': f'/api/video-thumbnail?folder={folder_q}&name={name_q}',
        })
    return jsonify({
        'videos': result,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total else 0,
    })

@app.route('/api/video-thumbnail')
def api_video_thumbnail():
    folder = resolve_video_folder(request.args.get('folder', ''))
    name = request.args.get('name', '')
    if not folder or not name or '/' in name or '..' in name:
        return '', 400
    fp = os.path.join(folder, name)
    if not os.path.isfile(fp):
        return '', 404
    tp = ensure_thumbnail(folder, name)
    if not tp:
        return '', 500
    return send_from_directory(THUMBNAILS_FOLDER, os.path.basename(tp))

@app.route('/api/video-file')
def api_video_file():
    folder = resolve_video_folder(request.args.get('folder', ''))
    name = request.args.get('name', '')
    if not folder or not name or '/' in name or '..' in name:
        return '', 400
    return send_from_directory(folder, name)

@app.route('/api/video-meta')
def api_video_meta():
    name = request.args.get('name', '')
    folder = resolve_video_folder(request.args.get('folder', ''))
    if not folder or not name or '/' in name or '..' in name:
        return jsonify({'error': 'invalid'}), 400
    fp = os.path.join(folder, name)
    if not os.path.exists(fp):
        return jsonify({'error': 'not found'}), 404
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', fp],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(probe.stdout)
        fmt = data.get('format', {})
        video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), {})
        duration = float(fmt.get('duration', 0))
        r_frame_rate = video_stream.get('r_frame_rate', '0/1')
        num, den = (int(x) for x in r_frame_rate.split('/'))
        fps = round(num / den, 3) if den else 0
        nb_frames = video_stream.get('nb_frames')
        total_frames = int(nb_frames) if nb_frames and nb_frames != 'N/A' else round(duration * fps)
        stat = os.stat(fp)
        creation_info_raw = fmt.get('tags', {}).get('description', '') or fmt.get('tags', {}).get('comment', '')
        if '_meta' in creation_info_raw:
            _meta_data = json.loads(creation_info_raw)
            prompt_dict = json.loads(_meta_data["prompt"])
            #creation_info = prompt_dict["373"]["inputs"]["text"]
            # 2. Loop through all nodes, extract text from inputs, and collect them
            all_texts = []
            for node_id, node_content in prompt_dict.items():
                inputs = node_content.get("inputs", {})
            # If the input contains a 'text' field, grab it
                if "text" in inputs:
                    all_texts.append(inputs["text"])    
            #creation_info = "\n".join(all_texts)
            creation_info = "\n =============================== \n".join(all_texts)
        else: creation_info = creation_info_raw
        return jsonify({
            'name': name,
            'size_bytes': stat.st_size,
            'created': stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime,
            'duration': duration,
            'width': video_stream.get('width', 0),
            'height': video_stream.get('height', 0),
            'fps': fps,
            'total_frames': total_frames,
            'creation_info': creation_info,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/video-update-meta', methods=['POST'])
def api_video_update_meta():
    data = request.get_json()
    name = data.get('name', '')
    folder = resolve_video_folder(data.get('folder', ''))
    creation_info = data.get('creation_info', '')
    if not folder or not name or '/' in name or '..' in name:
        return jsonify({'error': 'invalid'}), 400
    fp = os.path.join(folder, name)
    if not os.path.exists(fp):
        return jsonify({'error': 'not found'}), 404
    tmp = fp + '.tmp.mp4'
    try:
        result = subprocess.run(
            ['ffmpeg', '-i', fp, '-c', 'copy',
             '-metadata', f'description={creation_info}',
             '-metadata', f'comment={creation_info}',
             tmp, '-y'],
            capture_output=True#, text=True, timeout=60
        )
        # Decode while safely dropping or replacing unreadable characters
        stdout_text = result.stdout.decode("utf-8", errors="ignore")
        stderr_text = result.stderr.decode("utf-8", errors="replace")  # or 'cp1252' / 'latin-1'

        if result.returncode != 0:
            return jsonify({'error': result.stderr[-300:]}), 500
        os.replace(tmp, fp)
        return jsonify({'ok': True})
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return jsonify({'error': str(e)}), 500

@app.route('/api/video-delete', methods=['POST'])
def api_video_delete():
    data = request.get_json()
    names = data.get('names', [])
    folder = resolve_video_folder(data.get('folder', ''))
    if not folder:
        return jsonify({'error': 'invalid folder'}), 400
    deleted, errors = [], []
    for name in names:
        if not name or '/' in name or '..' in name:
            errors.append(name)
            continue
        fp = os.path.join(folder, name)
        try:
            os.remove(fp)
            remove_thumbnail(folder, name)
            deleted.append(name)
        except Exception as e:
            errors.append(name)
    return jsonify({'deleted': deleted, 'errors': errors})

@app.route('/videos/<path:filename>')
def serve_video(filename):
    return send_from_directory(VIDEOS_FOLDER, filename)

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
