"""Background job wrapper: writes a durable status file and uses resumable rendering.
"""
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone

from answer_tts import ROOT, main
from project_paths import audio_root

if '--output' in sys.argv:
    OUTPUT = Path(sys.argv[sys.argv.index('--output') + 1]).resolve()
else:
    OUTPUT = audio_root('edited' if '--emphasized-punctuation' in sys.argv else 'original')
STATUS = OUTPUT / 'generation_status.json'


def write_status(state, **details):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({'state': state, 'updated_utc': datetime.now(timezone.utc).isoformat(),
                                  **details}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    write_status('running', pid=os.getpid(), voice='af_heart' if '--voice' not in sys.argv
                 else sys.argv[sys.argv.index('--voice') + 1])
    # Keep automatic system sleep from pausing the job; reset when the process exits.
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        records = main()
    except BaseException as exc:
        write_status('failed', error=str(exc))
        traceback.print_exc()
        sys.exit(1)
    else:
        write_status('complete', answers=len(records or []),
                     audio_seconds=round(sum(r['duration_seconds'] for r in records or []), 3))
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
