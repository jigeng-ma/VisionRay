import sys
from pathlib import Path
ROOT = Path(sys.executable).resolve().parent.parent.parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--case-worker':
        sys.argv.pop(1)
        import json, traceback
        result = Path(sys.argv[2])
        result.parent.mkdir(parents=True, exist_ok=True)
        # windowed EXE 没有标准流；pytest 错误必须进入日志，不能停在隐藏错误窗口。
        if sys.stdout is None or sys.stderr is None:
            log = (result.parent/'worker-bootstrap.log').open('a', encoding='utf-8', buffering=1)
            sys.stdout = sys.stderr = log
        try:
            from studio.worker import main
            main()
        except BaseException:
            detail = traceback.format_exc()
            print(detail, flush=True)
            result.write_text(json.dumps({'status':'ERROR','detail':detail}, ensure_ascii=False), encoding='utf-8')
            sys.exit(1)
    else:
        from studio.ui import App
        App(ROOT).mainloop()
