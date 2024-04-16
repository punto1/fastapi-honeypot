from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from starlette.responses import Response

from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging

logprefix = datetime.utcnow().strftime("%Y%m%d%H%M")

def setup_logfile(prefix, fname, level=logging.INFO, format='%(asctime)s %(message)s'):
    logfile = "%s_%s" %(prefix, fname)
    formatter = logging.Formatter(format)
    fhandler = logging.FileHandler(logfile)
    fhandler.setFormatter(formatter)
    logger = logging.getLogger(fname)
    logger.setLevel(level)
    logger.addHandler(fhandler)
    return logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Listening! (logprefix: %s)" %logprefix)
    yield
    with open("testruns.txt", "a") as outpf:
        outpf.write("\n========\ntot. exec time on new db: %s\ntot. exec time on old db: %s\n" %(app.tot_exectime_new,  app.tot_exectime))
        outpf.write("nr calls: %s\n" %app.nr_calls)
        outpf.write("logging started at %s and ended at %s\n" %(logprefix, datetime.utcnow().strftime("%Y%m%d%H%M")))
        outpf.write("===\n\n")

    print("\n\n========\ntot. exec time on new db: %s\ntot. exec time on old db: %s" %(app.tot_exectime_new,  app.tot_exectime_old))
    print("nr calls: %s" %app.nr_calls)
    print("nr exceptions: %s" %app.nr_clientdisconnect)
    print("logging started at %s and ended at %s" %(logprefix, datetime.utcnow().strftime("%Y%m%d%H%M")))

app = FastAPI(lifespan=lifespan)
app.WRITE_LOGS = True
app.tot_exectime_new = 0.0
app.tot_exectime_old = 0.0
app.nr_calls = 0

log_newdb_slower = setup_logfile(logprefix, 'log_newdbslower')
log_newdb_faster = setup_logfile(logprefix, 'log_newdbfaster')
log_same = setup_logfile(logprefix, 'log_sameperf')
log_realslow = setup_logfile(logprefix, 'log_realslow')
#wslog = setup_logfile(logprefix, 'ws.log')

@app.middleware("http")
async def log_traffic(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    process_time = (datetime.now() - start_time).total_seconds()
    client_host = request.client.host
    #if await request.is_disconnected():
    #    app.nr_clientdisconnect += 1
    #https://github.com/gradio-app/gradio/issues/6393
    reqbody = await request.body()
    log_params = {
        "request_method": request.method,
        "request_url": str(request.url),
        "request_size": request.headers.get("content-length"),
        "request_headers": dict(request.headers),
        "request_body": reqbody,
        "response_status": response.status_code,
        "response_size": response.headers.get("content-length"),
        "response_headers": dict(response.headers),
        "process_time": process_time,
        "client_host": client_host
    }
    if app.WRITE_LOGS and response.status_code == 200:
        app.nr_calls += 1
        bodyparams = json.loads(reqbody)
        exec_time_ori = float(bodyparams.get('ori_exec_time'))
        exec_time_new = float(bodyparams.get('exec_time_newdb'))
        perf_factor = exec_time_ori/exec_time_new      
        log_params['perf_factor'] = str(round(perf_factor,2))
        if perf_factor > 1.1:
            log_newdb_faster.info(log_params)
        elif perf_factor < 0.95:
            log_newdb_slower.info(log_params)
        else:
            log_same.info(log_params)
        if exec_time_new > 0.5 or exec_time_ori > 0.7:
            log_realslow.info(log_params)
        app.tot_exectime_new += exec_time_new
        app.tot_exectime_old += exec_time_ori
    return response

# @app.api_route("/{rest_of_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.api_route("/{rest_of_path:path}", methods=["GET", "POST"])
async def catch_all(request: Request, rest_of_path: str):
    if rest_of_path.startswith('db-benchmark'):
        try:
            return Response(status_code=200)
        except Exception as exc: # starlette.requests.ClientDisconnect
            print(str(exc))
    return Response(status_code=418)


@app.websocket('/ws')
async def ws_catch_all(websocket: WebSocket):
    """
https://fastapi.tiangolo.com/advanced/websockets/#__tabbed_1_1
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            #wslog.info(str(data))
    except WebSocketDisconnect:
        pass
