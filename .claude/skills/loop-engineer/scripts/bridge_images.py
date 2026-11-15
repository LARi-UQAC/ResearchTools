import base64
from pathlib import Path
from typing import Dict, List, Optional, Union


class ImageError(ValueError):
    """Raised when an image file is invalid for attachment."""
    pass


def encode_images(files: List[Path], max_bytes: int) -> List[str]:
    """
    Purpose: Encode a list of image files into base64 strings.
    Inputs:
        files: List of paths to image files.
        max_bytes: Maximum allowed size in bytes for each file.
    Outputs:
        List of base64 encoded strings.
    Raises:
        ImageError: If a file is missing, empty, or larger than max_bytes.
    """
    encoded: List[str] = []
    for i, file_path in enumerate(files):
        pos = i + 1
        if not file_path.exists():
            raise ImageError(f"File at position {pos} is missing")
        
        size = file_path.stat().st_size
        if size == 0:
            raise ImageError(f"File at position {pos} is empty")
        
        if size > max_bytes:
            raise ImageError(f"File at position {pos} is larger than {max_bytes} bytes")
        
        data = file_path.read_bytes()
        encoded.append(base64.b64encode(data).decode("ascii"))
    
    return encoded


def attach_images(payload: Dict, files: Optional[List[Path]], max_bytes: int) -> Dict:
    """
    Purpose: Attach encoded images to a payload dictionary.
    Inputs:
        payload: The original payload dictionary.
        files: Optional list of paths to image files. If None or empty, no images are attached.
        max_bytes: Maximum allowed size in bytes for each file.
    Outputs:
        A new dictionary with an 'images' key if files were provided, otherwise a copy of the original.
    Raises:
        ImageError: Propagated from encode_images.
    """
    result = dict(payload)
    if files is None or len(files) == 0:
        return result
    
    result["images"] = encode_images(files, max_bytes)
    return result
