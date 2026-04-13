## Multi-core (single machine)
|Module|Verdict|
|---|---|
|multiprocessing (stdlib)|The primitive layer. Use it only if you need fine-grained Queue/Pipe/Value control. API is verbose and pickling failures are cryptic.|
|concurrent.futures.ProcessPoolExecutor (stdlib)|Best default choice. Clean submit()/map() API, integrates with asyncio via loop.run_in_executor(), no extra deps. Use this.|
|joblib|Better than ProcessPoolExecutor when your callables are numpy-heavy (avoids unnecessary pickle round-trips via memory-mapped arrays). The go-to for scikit-learn style workloads. Worth it if rasterio/numpy arrays are being passed between workers.|
|loky|What joblib uses internally. Solves multiprocessing spawn failures on Windows/macOS. Rarely used directly.|
|ray (local mode)|Overkill for 3 planners on one machine, but the API (@ray.remote) is elegant and scales to distributed later with zero code change.|

#### Opinion for your planner: Use ProcessPoolExecutor wrapped in asyncio's run_in_executor. Each planner runs in its own process, sidesteps the GIL entirely, and asyncio.gather coordinates the results cleanly:
```
loop = asyncio.get_event_loop()
with ProcessPoolExecutor(max_workers=len(planners)) as pool:
    futures = [loop.run_in_executor(pool, planner.run) for planner in planners]
    results = await asyncio.gather(*futures)
```

## Multi-machine (distributed)
|Module|Verdict|
|---|---|
|ray|Best modern choice. Zero-config local → distributed promotion, actor model maps naturally onto long-lived objects like RoutePlanner, handles large numpy array sharing via its object store. Active community.|
|dask.distributed|Best if your workload is already dataframe/array-shaped. dask.delayed and dask.graph are awkward for arbitrary callables; shines on bulk numerical work, less so on stateful planning objects.|
|Celery|Mature task queue, but requires an external broker (Redis/RabbitMQ) and a worker daemon. Heavy ops overhead for what amounts to "run these three functions in parallel." Designed for web-scale job queues, not compute tasks.|
|mpi4py|HPC-grade MPI bindings. Extremely fast collective operations, but the SPMD programming model is hostile to Python's object-oriented style. Only justify if you're running on a cluster with an MPI scheduler.|
|Prefect / Airflow|Workflow orchestrators, not execution engines. They call executors (Dask, Ray) under the hood. Wrong layer for this problem.|

#### Opinion: If you ever need to run planners across machines — e.g., to parallelise ARA*'s ε-iteration across a small cluster — adopt ray from the start. The @ray.remote decoration on RoutePlanner subclasses is minimal, local mode works identically to distributed mode, and it handles the LayerStore data-sharing problem gracefully via its distributed object store. The migration cost from ProcessPoolExecutor to ray later is non-trivial; starting with ray locally costs almost nothing.
