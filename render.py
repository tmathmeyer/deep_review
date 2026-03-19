#!/usr/bin/env python3
import sys
import os

from core.render import render_markdown

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path_to_markdown_file>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    rendered_output = render_markdown(content)
    print(rendered_output)

if __name__ == "__main__":
    main()
