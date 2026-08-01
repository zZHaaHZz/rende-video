import sys
from pathlib import Path

# Add capcut-tts-api to path
_HERE = Path(__file__).parent
_CC_DIR = _HERE / "capcut-tts-api"
if str(_CC_DIR) not in sys.path:
    sys.path.insert(0, str(_CC_DIR))

import capcut_common_task_client

# Monkey patch tts_new_body to use xml:lang="ko-KR"
original_tts_new_body = capcut_common_task_client.tts_new_body

def patched_tts_new_body(texts, voice, resource_id, rate, device):
    babi, body = original_tts_new_body(texts, voice, resource_id, rate, device)
    # Replace en-US with ko-KR in the body's SSML
    import json
    payload = json.loads(body["tasks"][0]["payload"])
    ssml = payload["ssml"]
    
    # Thay thế xml:lang="en-US" thành xml:lang="ko-KR"
    ssml_patched = ssml.replace('xml:lang="en-US"', 'xml:lang="ko-KR"')
    payload["ssml"] = ssml_patched
    
    # Re-sign the payload
    payload["sign"] = capcut_common_task_client.make_tts_payload_sign(
        ssml_patched, 
        payload["extra_info"], 
        device["device_id"], 
        device["aid"]
    )
    
    body["tasks"][0]["payload"] = capcut_common_task_client.compact_json(payload)
    return babi, body

capcut_common_task_client.tts_new_body = patched_tts_new_body

# Bây giờ import capcut_tts và chạy thử từ tiếng Hàn thuần túy (từ bị lỗi lúc nãy)
import capcut_tts

text = "명예퇴직금" # Từ này lúc nãy bị FAILED!
voice = "🇰🇷 여성 표준 (Standard Female)"

print(f"Testing patched xml:lang='ko-KR' with text: '{text}'...")
try:
    audio_path, _ = capcut_tts.tts_capcut(
        text=text,
        voice_key=voice,
        rate="1.0",
        out_path="test_ko_patch_success.mp3"
    )
    print("Success! Path:", audio_path)
except Exception as e:
    import traceback
    print("Failed with error:")
    traceback.print_exc()
