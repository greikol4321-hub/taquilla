"""
Load test simple para /api/stats y /api/listar — simula 20 usuarios concurrentes.
Ponytail: stdlib concurrent.futures + statistics, sin locust/k6 externo.
"""
import sys
sys.path.insert(0, r"D:\Trabajos Importantes\En desarrollo\Entradas")
from load_env import cargar_env
cargar_env()
from app import app
import time
import concurrent.futures
import statistics

def hit_stats(n):
    c = app.test_client()
    # login como grei para stats
    c.post('/api/login', json={'usuario':'grei','password':'grei2026'})
    start = time.perf_counter()
    r = c.get('/api/stats')
    elapsed = (time.perf_counter() - start)*1000
    return elapsed, r.status_code

def hit_dashboard(n):
    c = app.test_client()
    c.post('/api/login', json={'usuario':'grei','password':'grei2026'})
    start = time.perf_counter()
    r = c.get('/api/dashboard')
    elapsed = (time.perf_counter() - start)*1000
    return elapsed, r.status_code

def run(concurrency=20, per_user=10):
    print(f"Load test: {concurrency} hilos x {per_user} req cada uno")
    times = []
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = []
        for i in range(concurrency):
            for _ in range(per_user):
                futs.append(ex.submit(hit_stats, i))
        for f in concurrent.futures.as_completed(futs):
            ms, code = f.result()
            times.append(ms)
            if code != 200:
                errors += 1
    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times)*0.95)] if times else 0
    p99 = times[int(len(times)*0.99)] if times else 0
    print(f"Total req: {len(times)}, errores: {errors}")
    print(f"p50 {p50:.1f}ms p95 {p95:.1f}ms p99 {p99:.1f}ms min {min(times):.1f} max {max(times):.1f} avg {statistics.mean(times):.1f}ms")
    if p95 < 200:
        print("OK p95 <200ms")
    else:
        print("WARN p95 >200ms — considerar subir TTL o Redis")
    return p95

if __name__ == "__main__":
    run()
    print("--- dashboard ---")
    # dashboard test
    times=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs=[ex.submit(hit_dashboard,i) for i in range(20)]
        for f in concurrent.futures.as_completed(futs):
            ms,code=f.result()
            times.append(ms)
    print(f"dashboard p95 {sorted(times)[int(len(times)*0.95)]:.1f}ms")
