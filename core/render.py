import re

def setup_pygments() -> bool:
    try:
        import pygments
        return True
    except ImportError:
        return False

def render_markdown(text: str) -> str:
    """
    Renders markdown with ANSI escape sequences for the terminal.
    Parses ' - Line XX:' or ' - Line XX-YY:' and places the line number inline in the code block.
    Adds syntax highlighting using Pygments.
    """
    has_pygments = setup_pygments()

    if has_pygments:
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name, guess_lexer_for_filename
        from pygments.formatters import Terminal256Formatter
        from pygments.util import ClassNotFound

    lines = text.splitlines()
    rendered_lines = []
    
    current_file_name = None
    current_language_extension = ""
    
    line_index = 0
    
    while line_index < len(lines):
        current_line = lines[line_index]
        
        # Check for file header: ### `filename` or ### filename
        file_header_match = re.match(r'^###\s+`?([^`]+?)`?\s*$', current_line)
        if file_header_match:
            current_file_name = file_header_match.group(1).strip()
            current_language_extension = current_file_name.split('.')[-1] if '.' in current_file_name else ""
            rendered_lines.append(f"\n\033[1;36m### {current_file_name}\033[0m")
            line_index += 1
            continue
            
        # Check for regular headers: ## Header
        header_match = re.match(r'^(##+)\s+(.*)', current_line)
        if header_match:
            header_level = header_match.group(1)
            header_text = header_match.group(2)
            rendered_lines.append(f"\n\033[1;35m{header_level} {header_text}\033[0m")
            line_index += 1
            continue
            
        # Match ' - Line 123:', ' - Line 123-145:', ' - Line 255-256 and 330-331:', etc.
        line_annotation_match = re.match(r'^\s*-\s*Line[s]?\s+(\d+)[^:]*:', current_line)
        
        has_next_line = line_index + 1 < len(lines)
        is_next_line_code_block = False
        backtick_match = None
        
        if has_next_line:
            next_line = lines[line_index + 1].strip()
            backtick_match = re.match(r'^(`+)(.*)', next_line)
            if backtick_match:
                is_next_line_code_block = True
                
        if line_annotation_match and is_next_line_code_block:
            start_line_number = int(line_annotation_match.group(1))
            
            backticks_used = backtick_match.group(1)
            parsed_language = backtick_match.group(2).strip()
            
            if not parsed_language:
                parsed_language = current_language_extension
            if parsed_language in ("cc", "h"):
                parsed_language = "cpp"
            
            code_block_lines = []
            code_line_index = line_index + 2
            
            while code_line_index < len(lines):
                potential_end_line = lines[code_line_index].strip()
                if potential_end_line.startswith(backticks_used):
                    break
                code_block_lines.append(lines[code_line_index])
                code_line_index += 1
                
            numbered_code_lines = []
            for offset, code_line in enumerate(code_block_lines):
                # Optionally strip the 3 spaces of indent from the markdown block
                if code_line.startswith("   "):
                    code_line = code_line[3:]
                numbered_code_lines.append(f"{start_line_number + offset:4d} | {code_line}")
                
            code_string = "\n".join(numbered_code_lines)
            
            highlighted_code = code_string
            if has_pygments:
                try:
                    lexer = get_lexer_by_name(parsed_language)
                except ClassNotFound:
                    try:
                        if current_file_name:
                            lexer = guess_lexer_for_filename(current_file_name, code_string)
                        else:
                            lexer = get_lexer_by_name('text')
                    except ClassNotFound:
                        lexer = get_lexer_by_name('text')
                
                formatter = Terminal256Formatter(style='monokai')
                highlighted_code = highlight(code_string, lexer, formatter).strip()
            
            for highlighted_line in highlighted_code.splitlines():
                rendered_lines.append(highlighted_line)
            
            if code_line_index < len(lines):
                line_index = code_line_index + 1
            else:
                line_index = code_line_index
            continue
            
        agents_match = re.match(r'^\s*Agents:\s*(.*)', current_line)
        if agents_match:
            rendered_lines.append(f"  \033[33mAgents:\033[0m \033[1;34m{agents_match.group(1)}\033[0m")
            line_index += 1
            continue
            
        # Basic markdown formatting
        formatted_line = re.sub(r'\*\*(.*?)\*\*', r"\033[1m\1\033[0m", current_line)
        formatted_line = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r"\033[3m\1\033[0m", formatted_line)
        formatted_line = re.sub(r'`(.*?)`', r"\033[32m\1\033[0m", formatted_line)
        
        rendered_lines.append(formatted_line)
        line_index += 1
        
    return "\n".join(rendered_lines).strip()