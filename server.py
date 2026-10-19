import argparse, os
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    os.environ['EXPLAINER_PORT']=str(args.port)
    import uvicorn
    from backend.app import app
    import threading, time, signal
    parent=os.environ.get('EXPLAINER_PARENT_PID')
    if parent:
        def watch_parent():
            while True:
                time.sleep(1)
                if os.getppid()!=int(parent):
                    os.kill(os.getpid(),signal.SIGTERM);return
        threading.Thread(target=watch_parent,daemon=True).start()
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='warning',timeout_graceful_shutdown=2)
