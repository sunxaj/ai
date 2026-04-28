#!/usr/bin/env python3
"""
CLI Command:
# cd G:\Models\diffusion_models\qwen-image
# python model_conversion.py "G:\Models\diffusion_models\qwen-image\z-image_unstableRevolution_Bf16.safetensors" "G:\Models\diffusion_models\qwen-image\z-image_unstableRevolution.gguf" -q q8_k_M

Model conversion utilities for converting safetensors to GGUF format.
Supports fp16 and q8_k_M quantization.
"""

import struct
import numpy as np
from pathlib import Path
from typing import Literal, Optional
import json


def convert_safetensors_to_gguf(
    input_path: str,
    output_path: str,
    quantization: Literal["full", "q8_0", "q8_k_M"] = "full",
    metadata: Optional[dict] = None
) -> None:
    """
    Convert z-image safetensors (fp16/bf16) to GGUF format.
    
    Args:
        input_path: Path to input safetensors file (supports fp16, bf16 formats)
        output_path: Path to output GGUF file
        quantization: Quantization type - "full" (fp16), "q8_0" or "q8_k_M" (8-bit quantized)
        metadata: Optional metadata dictionary to include in GGUF file
    
    Example:
        >>> convert_safetensors_to_gguf("model.safetensors", "model.gguf", "q8_k_M")
    
    Note:
        bf16 tensors are automatically converted to fp32 for processing, then to fp16 or quantized.
    """
    try:
        from safetensors import safe_open
    except ImportError:
        raise ImportError("safetensors library required. Install with: pip install safetensors")
    
    input_file = Path(input_path)
    output_file = Path(output_path)
    
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    print(f"Loading safetensors from {input_file}...")
    
    # Load tensors from safetensors
    # Try PyTorch first to handle bfloat16, fallback to numpy
    tensors = {}
    try:
        import torch
        use_torch = True
        print("  Using PyTorch backend for bfloat16 support")
    except ImportError:
        use_torch = False
        print("  Using NumPy backend (PyTorch not available)")
    
    try:
        framework = "pt" if use_torch else "numpy"
        with safe_open(input_file, framework=framework) as f:
            for key in f.keys():
                tensor = f.get_tensor(key)
                
                # Convert PyTorch tensor to numpy
                if use_torch:
                    if tensor.dtype == torch.bfloat16:
                        # Convert bf16 to fp32 for processing
                        tensor = tensor.float().numpy()
                        print(f"  Converted {key} from bf16 to fp32")
                    else:
                        tensor = tensor.numpy()
                
                tensors[key] = tensor
    except Exception as e:
        if "bfloat16" in str(e).lower() and not use_torch:
            raise RuntimeError(
                "bfloat16 tensors detected but PyTorch is not installed. "
                "Install PyTorch to handle bf16: pip install torch"
            )
        raise
    
    print(f"Loaded {len(tensors)} tensors")
    
    # Convert to GGUF format
    print(f"Converting to GGUF format with {quantization} quantization...")
    
    with open(output_file, 'wb') as f:
        # Write GGUF magic number and version
        f.write(b'GGUF')  # Magic
        f.write(struct.pack('I', 3))  # Version 3
        
        # Write tensor count and metadata count
        f.write(struct.pack('Q', len(tensors)))  # Tensor count
        
        # Write metadata
        metadata_dict = metadata or {}
        file_type = 1 if quantization == "full" else 7  # 1=fp16, 7=q8_0/q8_k
        metadata_dict.update({
            'general.architecture': 'zimage',
            'general.quantization_version': 2,
            'general.file_type': file_type
        })
        
        f.write(struct.pack('Q', len(metadata_dict)))  # Metadata count
        
        for key, value in metadata_dict.items():
            # Write key
            key_bytes = key.encode('utf-8')
            f.write(struct.pack('Q', len(key_bytes)))
            f.write(key_bytes)
            
            # Write value type and value
            if isinstance(value, str):
                f.write(struct.pack('I', 8))  # String type
                val_bytes = value.encode('utf-8')
                f.write(struct.pack('Q', len(val_bytes)))
                f.write(val_bytes)
            elif isinstance(value, int):
                f.write(struct.pack('I', 4))  # Int32 type
                f.write(struct.pack('i', value))
            elif isinstance(value, float):
                f.write(struct.pack('I', 5))  # Float32 type
                f.write(struct.pack('f', value))
        
        # Write tensor info
        tensor_data_offset = f.tell() + sum(
            8 + len(name.encode('utf-8')) + 16 + 8 * len(tensor.shape) + 8
            for name, tensor in tensors.items()
        )
        
        current_offset = 0
        for name, tensor in tensors.items():
            # Quantize if needed
            if quantization == "q8_0":
                quantized_data = quantize_q8_0(tensor)
                tensor_bytes = quantized_data
            elif quantization == "q8_k_M":
                quantized_data = quantize_q8_k_M(tensor)
                tensor_bytes = quantized_data
            else:
                # Keep as fp16
                if tensor.dtype != np.float16:
                    tensor = tensor.astype(np.float16)
                tensor_bytes = tensor.tobytes()
            
            # Write tensor name
            name_bytes = name.encode('utf-8')
            f.write(struct.pack('Q', len(name_bytes)))
            f.write(name_bytes)
            
            # Write tensor dimensions
            f.write(struct.pack('I', len(tensor.shape)))
            for dim in tensor.shape:
                f.write(struct.pack('Q', dim))
            
            # Write tensor type
            if quantization in ["q8_0", "q8_k_M"]:
                f.write(struct.pack('I', 7))  # Q8_0 type
            else:
                f.write(struct.pack('I', 1))  # FP16 type
            
            # Write offset
            f.write(struct.pack('Q', tensor_data_offset + current_offset))
            
            current_offset += len(tensor_bytes)
        
        # Align to 32 bytes
        alignment = 32
        padding = (alignment - (f.tell() % alignment)) % alignment
        f.write(b'\x00' * padding)
        
        # Write tensor data
        for name, tensor in tensors.items():
            if quantization == "q8_0":
                quantized_data = quantize_q8_0(tensor)
                f.write(quantized_data)
            elif quantization == "q8_k_M":
                quantized_data = quantize_q8_k_M(tensor)
                f.write(quantized_data)
            else:
                if tensor.dtype != np.float16:
                    tensor = tensor.astype(np.float16)
                f.write(tensor.tobytes())
    
    print(f"✓ Conversion complete: {output_file}")
    print(f"  File size: {output_file.stat().st_size / (1024**2):.2f} MB")


def quantize_q8_0(tensor: np.ndarray) -> bytes:
    """
    Quantize tensor to Q8_0 format (simple 8-bit quantization with fp16 scaling).
    
    Args:
        tensor: Input tensor (fp16, fp32, or bf16 converted to fp32)
    
    Returns:
        Quantized data as bytes (fp16 scale factors + int8 quantized values per block)
    """
    # Ensure float32 for quantization
    if tensor.dtype != np.float32:
        tensor = tensor.astype(np.float32)
    
    # Flatten tensor
    flat = tensor.flatten()
    
    # Block size for Q8_0
    block_size = 32
    n_blocks = (len(flat) + block_size - 1) // block_size
    
    quantized = bytearray()
    
    for i in range(n_blocks):
        start = i * block_size
        end = min(start + block_size, len(flat))
        block = flat[start:end]
        
        # Calculate scale factor
        abs_max = np.abs(block).max()
        if abs_max == 0:
            scale = 0.0
        else:
            scale = abs_max / 127.0
        
        # Write scale as fp16
        scale_fp16 = np.float16(scale)
        quantized.extend(struct.pack('e', scale_fp16))
        
        # Quantize values to int8
        if scale > 0:
            quantized_block = np.round(block / scale).astype(np.int8)
        else:
            quantized_block = np.zeros(len(block), dtype=np.int8)
        
        quantized.extend(quantized_block.tobytes())
        
        # Pad to block_size if needed
        if len(block) < block_size:
            quantized.extend(b'\x00' * (block_size - len(block)))
    
    return bytes(quantized)


def quantize_q8_k_M(tensor: np.ndarray) -> bytes:
    """
    Quantize tensor to Q8_K_M format (8-bit quantization with scaling).
    
    Args:
        tensor: Input tensor (fp16, fp32, or bf16 converted to fp32)
    
    Returns:
        Quantized data as bytes (scale factors + int8 quantized values)
    """
    # Ensure float32 for quantization
    if tensor.dtype != np.float32:
        tensor = tensor.astype(np.float32)
    
    # Flatten tensor
    flat = tensor.flatten()
    
    # Block size for Q8_K
    block_size = 256
    n_blocks = (len(flat) + block_size - 1) // block_size
    
    quantized = bytearray()
    
    for i in range(n_blocks):
        start = i * block_size
        end = min(start + block_size, len(flat))
        block = flat[start:end]
        
        # Calculate scale factor
        abs_max = np.abs(block).max()
        if abs_max == 0:
            scale = 0.0
        else:
            scale = abs_max / 127.0
        
        # Write scale (fp32)
        quantized.extend(struct.pack('f', scale))
        
        # Quantize values to int8
        if scale > 0:
            quantized_block = np.round(block / scale).astype(np.int8)
        else:
            quantized_block = np.zeros(len(block), dtype=np.int8)
        
        quantized.extend(quantized_block.tobytes())
        
        # Pad to block_size if needed
        if len(block) < block_size:
            quantized.extend(b'\x00' * (block_size - len(block)))
    
    return bytes(quantized)


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Convert z-image fp16 safetensors to GGUF format"
    )
    parser.add_argument("input", help="Input safetensors file")
    parser.add_argument("output", help="Output GGUF file")
    parser.add_argument(
        "-q", "--quantization",
        choices=["full", "q8_0", "q8_k_M"],
        default="full",
        help="Quantization type: full/fp16 (default), q8_0 (8-bit simple), q8_k_M (8-bit advanced)"
    )
    parser.add_argument(
        "-m", "--metadata",
        help="JSON file with additional metadata"
    )
    
    args = parser.parse_args()
    
    metadata = None
    if args.metadata:
        with open(args.metadata) as f:
            metadata = json.load(f)
    
    convert_safetensors_to_gguf(
        args.input,
        args.output,
        args.quantization,
        metadata
    )
