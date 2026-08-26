import os
import cv2
import numpy as np
import insightface
from PIL import Image
from sklearn import preprocessing
import torch
import onnxruntime
import scripts.swapper as roop_swapper
from modules.processing import StableDiffusionProcessingImg2Img
from scripts.faceswap import FaceSwapScript, get_models
from utils import batch_tensor_to_pil, batched_pil_to_tensor, tensor_to_pil
from logging_patch import apply_logging_patch

FACES_EMBEDDINGS = []
EMBEDDING_PATH = os.path.expanduser("~/ComfyUI/embeddings")
EMBEDDING_THRESHOLD = 1.3
USE_EMBEDDING = False
FACE_ANALYSER = None
PROVIDERS = roop_swapper.providers
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
OCCLUDER_MODEL = None
FACEPARSER_MODEL = None
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ComfyUI_roop/models/roop")


def is_img(path):
    return str(path).lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))


def feature_compare(feature1, feature2, threshold):
    diff = np.subtract(feature1, feature2)
    dist = np.sum(np.square(diff), axis=1)
    return bool(dist[0] < threshold)


def get_face_analyser():
    global FACE_ANALYSER
    if FACE_ANALYSER is None:
        FACE_ANALYSER = insightface.app.FaceAnalysis(
            name="buffalo_l",
            providers=roop_swapper.providers,
            root=roop_swapper.insightface_path,
        )
        FACE_ANALYSER.prepare(ctx_id=0, det_size=(640, 640))
    return FACE_ANALYSER


def load_embedding(use_embedding, embedding_path="~/ComfyUI/embeddings", threshold=1.5):
    global FACES_EMBEDDINGS, EMBEDDING_PATH, EMBEDDING_THRESHOLD, USE_EMBEDDING
    FACES_EMBEDDINGS = []
    EMBEDDING_THRESHOLD = threshold
    if not use_embedding:
        EMBEDDING_PATH = ""
        USE_EMBEDDING = False
        print("***** Use No-Embedding Mode ********")
        return None

    EMBEDDING_PATH = os.path.expanduser(embedding_path or "~/ComfyUI/embeddings")
    USE_EMBEDDING = True
    if not os.path.isdir(EMBEDDING_PATH):
        print(f"<---- Embedding path not found: {EMBEDDING_PATH} ---->")
        USE_EMBEDDING = False
        return None

    embeddings = [x for x in os.listdir(EMBEDDING_PATH) if is_img(x)]
    if not embeddings:
        print("<---- No embedding found, use no embedding mode ---->")
        FACES_EMBEDDINGS = []
        USE_EMBEDDING = False
        return None

    for img_name in embeddings:
        img_path = os.path.join(EMBEDDING_PATH, img_name)
        face = roop_swapper.get_face_single(cv2.imread(img_path), face_index=0)
        if face:
            embedding = np.array(face.embedding).reshape((1, -1))
            embedding = preprocessing.normalize(embedding)
            FACES_EMBEDDINGS.append({
                "name": img_name,
                "feature": embedding,
            })
            print(f"---- {img_name} has valid embedding ----")
        else:
            print(f"---- {img_name} has no face detected ----")

    if FACES_EMBEDDINGS == []:
        print("<---- No valid embeddings found, use no embedding mode ---->")
        USE_EMBEDDING = False


def get_onnx_model(model_attr, model_path, input_name, input_shape, output_name, output_shape):
    model = globals().get(model_attr)
    if model is None or model == []:
        model = onnxruntime.InferenceSession(model_path, providers=PROVIDERS)
        globals()[model_attr] = model
    return model


def run_occluder(image, output):
    global OCCLUDER_MODEL
    model_path = os.path.join(MODELS_DIR, "occluder.onnx")
    if not OCCLUDER_MODEL:
        OCCLUDER_MODEL = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    inp = image.cpu().numpy()
    result = OCCLUDER_MODEL.run(["output"], {"img": inp})[0]
    output.copy_(torch.from_numpy(result).to(output.device))


def run_faceparser(image, output):
    global FACEPARSER_MODEL
    model_path = os.path.join(MODELS_DIR, "faceparser_fp16.onnx")
    if not FACEPARSER_MODEL:
        FACEPARSER_MODEL = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    inp = image.cpu().numpy()
    result = FACEPARSER_MODEL.run(["out"], {"input": inp})[0]
    output.copy_(torch.from_numpy(result).to(output.device))


def get_mouth_mask(image_pil):
    """Returns a PIL 'L' mask (255=keep original mouth, 0=allow swap) at original image size."""
    orig_w, orig_h = image_pil.size
    # ImageNet normalization gives best lip label coverage for this model
    inp_t = pil_image_to_tensor(image_pil, size=(512, 512), normalize_imagenet=True)

    out = torch.empty((1, 19, 512, 512), dtype=torch.float32, device=DEVICE)
    run_faceparser(inp_t, out)

    # label 11 (mouth) is inactive in this model — only 12 (u_lip) and 13 (l_lip) fire
    labels = torch.argmax(out.squeeze(0), dim=0)  # (512, 512)
    mouth_pixels = torch.isin(labels, torch.tensor([12, 13], device=DEVICE))
    count = mouth_pixels.sum().item()
    print(f"[faceparser] mouth pixels detected: {count}")

    mouth_mask = mouth_pixels.cpu().numpy().astype(np.uint8) * 255
    mask_pil = Image.fromarray(mouth_mask, mode="L")
    return mask_pil.resize((orig_w, orig_h), Image.NEAREST)


_original_roop_get_face_single = roop_swapper.get_face_single

def get_face_single_with_embedding(img_data, face_index=0, det_size=(640, 640), sorter="left to right", reverse_order=False):
    if USE_EMBEDDING and FACES_EMBEDDINGS:
        # ignore face_index/sorter — scan all faces and return the one matching the embedding
        # return None for face_index > 0 to avoid swapping the same face multiple times
        if face_index > 0:
            return None
        faces = get_face_analyser().get(img_data)
        for face in faces:
            embedding = np.array(face.embedding).reshape((1, -1))
            embedding = preprocessing.normalize(embedding)
            for embedding_tpl in FACES_EMBEDDINGS:
                if feature_compare(embedding, embedding_tpl["feature"], threshold=EMBEDDING_THRESHOLD):
                    return face
        return None
    return _original_roop_get_face_single(
        img_data,
        face_index=face_index,
        det_size=det_size,
        sorter=sorter,
        reverse_order=reverse_order,
    )


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD  = (0.229, 0.224, 0.225)

def pil_image_to_tensor(image, size=None, normalize_imagenet=False):
    arr = np.array(image).astype(np.float32) / 255.0
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if size is not None:
        arr = cv2.resize(arr, size, interpolation=cv2.INTER_LINEAR)
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(DEVICE)
    if normalize_imagenet:
        mean = torch.tensor(IMAGENET_MEAN, device=DEVICE).view(1, 3, 1, 1)
        std  = torch.tensor(IMAGENET_STD,  device=DEVICE).view(1, 3, 1, 1)
        tensor = (tensor - mean) / std
    return tensor


def tensor_to_pil_image(tensor):
    image = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()
    image = np.clip(image * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(image)


def apply_optional_occluder(image_pil):
    """Returns (masked_source_pil, occluder_mask_pil) where mask 255=occluded area."""
    orig_w, orig_h = image_pil.size
    img = pil_image_to_tensor(image_pil, size=(256, 256))
    out = torch.empty((1, 1, 256, 256), dtype=torch.float32, device=DEVICE)
    run_occluder(img, out)
    mask = (out > 0.5).float()  # 1=face, 0=occluded
    processed = (img * mask).clamp(0, 1)
    result = tensor_to_pil_image(processed).resize((orig_w, orig_h), Image.LANCZOS)
    # occluder_mask: 255 where occluded (mask==0), 0 where face is clear
    occluder_mask = ((1.0 - mask) * 255).squeeze().cpu().numpy().astype(np.uint8)
    occluder_mask_pil = Image.fromarray(occluder_mask, mode="L").resize((orig_w, orig_h), Image.NEAREST)
    return result, occluder_mask_pil


def apply_optional_faceparser(image_pil):
    """Segments the face and returns only the face region (non-background)."""
    orig_w, orig_h = image_pil.size
    img = pil_image_to_tensor(image_pil, size=(512, 512), normalize_imagenet=True)
    out = torch.empty((1, 19, 512, 512), dtype=torch.float32, device=DEVICE)
    run_faceparser(img, out)
    labels = torch.argmax(out.squeeze(0), dim=0)  # (512, 512)
    # exclude background classes: 0=bg, 14=neck, 15=neck_l, 16=cloth, 17=hair, 18=hat
    # note: label 11 (mouth) is inactive in this model; lips are 12/13
    bg_idxs = torch.tensor([0, 14, 15, 16, 17, 18], device=DEVICE)
    face_mask = (~torch.isin(labels, bg_idxs)).float().unsqueeze(0).unsqueeze(0)  # (1,1,512,512)
    # reconstruct unnormalized image for output
    img_raw = pil_image_to_tensor(image_pil, size=(512, 512))
    processed = (img_raw * face_mask).clamp(0, 1)
    result = tensor_to_pil_image(processed)
    return result.resize((orig_w, orig_h), Image.LANCZOS)


def disable_embedding():
    global FACES_EMBEDDINGS, EMBEDDING_PATH, USE_EMBEDDING
    FACES_EMBEDDINGS = []
    EMBEDDING_PATH = os.path.expanduser("~/ComfyUI/embeddings")
    USE_EMBEDDING = False


def patch_swapped_get_face_single():
    if getattr(roop_swapper, "_roop_embedding_patched", False):
        return
    roop_swapper.get_face_single = get_face_single_with_embedding
    roop_swapper._roop_embedding_patched = True


def model_names():
    models = get_models()
    return {os.path.basename(x): x for x in models}


ORDERINGS = ["left to right", "up to down", "largest to smallest"]
DEFAULT_ORDERING = ORDERINGS[0]

class roop:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "reference_image": ("IMAGE",),
                "swap_model": (list(model_names().keys()),),
                # Comma separated face number(s)
                "faces_index": ("STRING", {"default": "0"}),
                "reference_faces_index": ("STRING", {"default": "0"}),
                # Allow user to change the logging amount, going from minimal to verbose
                "console_logging_level": ([0, 1, 2],),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "roop"

    def execute(self, image, reference_image, swap_model, faces_index, reference_faces_index, console_logging_level):
        apply_logging_patch(console_logging_level)

        script = FaceSwapScript()
        pil_images = batch_tensor_to_pil(image)
        source = tensor_to_pil(reference_image)
        p = StableDiffusionProcessingImg2Img(pil_images)
        face_order = DEFAULT_ORDERING
        reverse_order = False
        reference_order = DEFAULT_ORDERING
        reverse_reference_order = False
        script.process(
            p=p, img=source, enable=True, faces_index=faces_index,
            reference_faces_index=reference_faces_index,
            face_order=face_order, reverse_order=reverse_order,
            reference_order=reference_order, reverse_reference_order=reverse_reference_order,
            model=swap_model,
            face_restorer_name=None, face_restorer_visibility=None,
            upscaler_name=None, upscaler_scale=None, upscaler_visibility=None,
            swap_in_source=True, swap_in_generated=True
        )
        result = batched_pil_to_tensor(p.init_images)
        return (result,)


class RoopImproved:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "reference_image": ("IMAGE",),
                "swap_model": (list(model_names().keys()),),
                # Comma separated face number(s)
                "faces_index": ("STRING", {"default": "0"}),
                "reference_faces_index": ("STRING", {"default": "0"}),
                "face_order": (ORDERINGS, {"default": DEFAULT_ORDERING}),
                "reverse_order": ("BOOLEAN", {"default": False}),
                "reference_order": (ORDERINGS, {"default": DEFAULT_ORDERING}),
                "reverse_reference_order": ("BOOLEAN", {"default": False}),
                "use_embedding": ("BOOLEAN", {"default": False}),
                "embedding_path": ("STRING", {"default": "~/ComfyUI/embeddings"}),
                "embedding_threshold": ("STRING", {"default": "1.5"}),
                "use_occluder": ("BOOLEAN", {"default": False}),
                "use_faceparser": ("BOOLEAN", {"default": False}),
                # Allow user to change the logging amount, going from minimal to verbose
                "console_logging_level": ([0, 1, 2],),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "roop"

    def execute(self, image, reference_image, swap_model, faces_index, reference_faces_index, face_order, reverse_order, reference_order, reverse_reference_order, use_embedding, embedding_path, embedding_threshold="1.3", use_occluder=False, use_faceparser=False, console_logging_level=0):
        apply_logging_patch(console_logging_level)

        embedding_path = os.path.expanduser(embedding_path or "~/ComfyUI/embeddings")
        if use_embedding:
            if os.path.isdir(embedding_path):
                embeddings = [x for x in os.listdir(embedding_path) if is_img(x)]
                if embeddings:
                    load_embedding(1, embedding_path, threshold=float(embedding_threshold))
                else:
                    print(f"<---- Embedding folder empty: {embedding_path}. Skipping embedding load. ---->")
                    disable_embedding()
            else:
                print(f"<---- Embedding path missing: {embedding_path}. Skipping embedding load. ---->")
                disable_embedding()
        else:
            load_embedding(0, embedding_path)

        patch_swapped_get_face_single()

        script = FaceSwapScript()
        pil_images = batch_tensor_to_pil(image)
        source = tensor_to_pil(reference_image)
        occluder_masks = None
        if use_occluder:
            source, occluder_mask = apply_optional_occluder(source)
            # build per-target occluder masks at target resolution
            occluder_masks = [occluder_mask.resize(img.size, Image.NEAREST) for img in pil_images]
        if use_faceparser:
            source = apply_optional_faceparser(source)

        # capture mouth masks from each target image before swapping
        mouth_masks = [get_mouth_mask(img) for img in pil_images] if use_faceparser else None

        p = StableDiffusionProcessingImg2Img(pil_images)
        script.process(
            p=p, img=source, enable=True, faces_index=faces_index,
            reference_faces_index=reference_faces_index,
            face_order=face_order, reverse_order=reverse_order,
            reference_order=reference_order, reverse_reference_order=reverse_reference_order,
            model=swap_model,
            face_restorer_name=None, face_restorer_visibility=None,
            upscaler_name=None, upscaler_scale=None, upscaler_visibility=None,
            swap_in_source=True, swap_in_generated=True
        )

        # composite original mouth back over swapped result
        # Image.composite(A, B, mask): mask=255 -> A, mask=0 -> B
        # We want: mouth region (mask=255) -> original, rest (mask=0) -> swapped
        if mouth_masks is not None:
            for i, (swapped, original, mask) in enumerate(zip(p.init_images, pil_images, mouth_masks)):
                if swapped is not None:
                    swapped_rgba = swapped.convert("RGBA") if swapped.mode != "RGBA" else swapped
                    original_rgba = original.convert("RGBA") if original.mode != "RGBA" else original
                    # paste original mouth pixels onto swapped result
                    swapped_rgba.paste(original_rgba, mask=mask)
                    p.init_images[i] = swapped_rgba.convert("RGB")

        # paste original target pixels back where occluder detected occlusion
        if occluder_masks is not None:
            for i, (swapped, original, mask) in enumerate(zip(p.init_images, pil_images, occluder_masks)):
                if swapped is not None:
                    swapped_rgba = swapped.convert("RGBA") if swapped.mode != "RGBA" else swapped
                    original_rgba = original.convert("RGBA") if original.mode != "RGBA" else original
                    swapped_rgba.paste(original_rgba, mask=mask)
                    p.init_images[i] = swapped_rgba.convert("RGB")

        result = batched_pil_to_tensor(p.init_images)
        return (result,)


NODE_CLASS_MAPPINGS = {
    "roop": roop,
    "RoopImproved": RoopImproved,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "roop": "roop",
    "RoopImproved": "Roop (Improved)",
}
