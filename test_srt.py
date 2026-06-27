import re

def shift_srt_time(time_str, offset_sec):
    # time_str: 00:00:01,234
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    total_sec = int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0 + offset_sec
    
    nh = int(total_sec // 3600)
    nm = int((total_sec % 3600) // 60)
    ns = int(total_sec % 60)
    nms = int(round((total_sec - int(total_sec)) * 1000))
    return f"{nh:02d}:{nm:02d}:{ns:02d},{nms:03d}"

def merge_srts(srt_files, audio_durations, output_file):
    # srt_files: list of paths to srt
    # audio_durations: list of exact audio durations for each scene (to know the offset)
    out_lines = []
    sub_index = 1
    current_offset = 0.0
    
    for srt, dur in zip(srt_files, audio_durations):
        if not srt or not open(srt).read().strip():
            current_offset += dur
            continue
            
        with open(srt, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        blocks = content.split('\n\n')
        for block in blocks:
            lines = block.split('\n')
            if len(lines) >= 3:
                # lines[0] is index, lines[1] is time, lines[2:] is text
                time_line = lines[1]
                match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_line)
                if match:
                    t1 = shift_srt_time(match.group(1), current_offset)
                    t2 = shift_srt_time(match.group(2), current_offset)
                    out_lines.append(str(sub_index))
                    out_lines.append(f"{t1} --> {t2}")
                    out_lines.extend(lines[2:])
                    out_lines.append("")
                    sub_index += 1
        current_offset += dur
        
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(out_lines))

print("SRT merger defined.")
