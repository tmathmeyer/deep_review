import re

def render_markdown(text: str) -> str:
    """
    Renders markdown with ANSI escape sequences for the terminal.
    Parses ' - Line XX:' and places the line number inline in the code block.
    Adds syntax highlighting using Pygments.
    """
    try:
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name, guess_lexer_for_filename
        from pygments.formatters import Terminal256Formatter
        from pygments.util import ClassNotFound
        has_pygments = True
    except ImportError:
        has_pygments = False

    lines = text.splitlines()
    out_lines = []
    
    current_file = None
    current_lang = ""
    
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check for file header
        m_file = re.match(r'^###\s+`([^`]+)`', line)
        if m_file:
            current_file = m_file.group(1)
            ext = current_file.split('.')[-1] if '.' in current_file else ""
            current_lang = ext
            out_lines.append(f"\n\033[1;36m### {current_file}\033[0m")
            i += 1
            continue
            
        m_header = re.match(r'^(##+)\s+(.*)', line)
        if m_header:
            out_lines.append(f"\n\033[1;35m{m_header.group(1)} {m_header.group(2)}\033[0m")
            i += 1
            continue
            
        # Match ' - Line 123:' immediately followed by a code block
        m_line = re.match(r'^\s*-\s*Line\s+(\d+):', line)
        if m_line and i + 1 < len(lines) and lines[i+1].strip().startswith('```'):
            start_line_num = int(m_line.group(1))
            block_start = lines[i+1].strip()
            lang = block_start[3:].strip()
            if not lang:
                lang = current_lang
            if lang in ("cc", "h"):
                lang = "cpp"
            
            code_lines = []
            j = i + 2
            while j < len(lines) and not lines[j].strip().startswith('```'):
                code_lines.append(lines[j])
                j += 1
                
            numbered_code = []
            for k, code_line in enumerate(code_lines):
                # Optionally strip the 3 spaces of indent from the markdown block
                if code_line.startswith("   "):
                    code_line = code_line[3:]
                numbered_code.append(f"{start_line_num + k:4d} | {code_line}")
                
            code_str = "\n".join(numbered_code)
            
            if has_pygments:
                try:
                    lexer = get_lexer_by_name(lang)
                except ClassNotFound:
                    try:
                        if current_file:
                            lexer = guess_lexer_for_filename(current_file, code_str)
                        else:
                            lexer = get_lexer_by_name('text')
                    except ClassNotFound:
                        lexer = get_lexer_by_name('text')
                
                formatter = Terminal256Formatter(style='monokai')
                highlighted = highlight(code_str, lexer, formatter).strip()
            else:
                highlighted = code_str
            
            for hl_line in highlighted.splitlines():
                out_lines.append(hl_line)
            
            if j < len(lines):
                i = j + 1
            else:
                i = j
            continue
            
        m_agents = re.match(r'^\s*Agents:\s*(.*)', line)
        if m_agents:
            out_lines.append(f"  \033[33mAgents:\033[0m \033[1;34m{m_agents.group(1)}\033[0m")
            i += 1
            continue
            
        # Basic markdown formatting
        line = re.sub(r'\*\*(.*?)\*\*', r"\033[1m\1\033[0m", line)
        line = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r"\033[3m\1\033[0m", line)
        line = re.sub(r'`(.*?)`', r"\033[32m\1\033[0m", line)
        
        out_lines.append(line)
        i += 1
        
    return "\n".join(out_lines).strip()
