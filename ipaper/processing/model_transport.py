"""One-shot model transport child. No credentials in argv, environment or files."""
import json
import sys
from .translation import request_once

def main():
    payload=sys.stdin.buffer.read(256*1024+1)
    if len(payload)>256*1024: raise ValueError("model_input_too_large")
    value=json.loads(payload)
    response=request_once(value["profile"],value["messages"],value["outputLimit"])
    sys.stdout.write(json.dumps(response,ensure_ascii=False,allow_nan=False))
    sys.stdout.flush()

if __name__=="__main__":main()
