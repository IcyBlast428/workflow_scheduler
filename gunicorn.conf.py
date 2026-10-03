def worker_exit(server, worker):
    from app.bootstrap.execution import stop_all_tasks
    stop_all_tasks()
