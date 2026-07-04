import json


def save_analysis_to_file(content, filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as f: 
        f.write(
            json.dumps(content, indent=2, ensure_ascii=False)
        )