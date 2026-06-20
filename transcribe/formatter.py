from pathlib import Path
import json, ast


def format_single_file(file_path: Path) -> None:

    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
    
    # Parse the Python literal
    try: segments = ast.literal_eval(content)
    
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Failed to parse {file_path.name}: {e}")
    
    # Write as formatted JSON
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)
    
    file_path.rename(file_path.with_suffix('.json'))
    
    print(f"{file_path.name} ({len(segments)} segments)")
    

def format_transcription_segments(path: str) -> None:
    
    path = Path(path)
    
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    
    # If it's a file, process it
    if path.is_file(): format_single_file(path)
    
    # If it's a directory, process all transcription segment files
    elif path.is_dir():
        segment_files = sorted(path.glob("*_transcription_segments.txt"))
        if segment_files:
            for file in segment_files: format_single_file(file)
            print(f"Formatted {len(segment_files)} file(s)")
    else:
        raise ValueError(f"Path is neither a file nor a directory: {path}")