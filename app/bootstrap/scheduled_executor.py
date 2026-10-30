from app.bootstrap.timebase import business_time
"""Attach the exact fire time while retaining APScheduler's runner semantics."""
import copy
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.executors.base import run_job


def run_with_times(job, run_times, logger_name):
    events = []
    for run_time in run_times:
        invocation = copy.copy(job)
        if job.func.__name__ in ('execute_py','execute_manual') and not job.kwargs.get('run_id'):
            invocation.kwargs = dict(job.kwargs,scheduled_time=business_time(run_time).isoformat(' '))
        events.extend(run_job(invocation,job._jobstore_alias,[run_time],logger_name))
    return events


class ScheduledExecutor(ThreadPoolExecutor):
    def submit_job(self, job, run_times):
        from app.bootstrap.execution import execute_py
        if job.func is execute_py:
            # Persist on the scheduler thread before acknowledging the firing. No
            # business subprocess and no unbounded in-memory executor queue here.
            from app.bootstrap.execution_requests import enqueue_scheduled
            for planned in run_times:
                enqueue_scheduled(job, planned)
            return
        return super().submit_job(job,run_times)

    def _do_submit_job(self, job, run_times):
        def done(future):
            error = future.exception()
            if error:
                self._run_job_error(job.id,error,error.__traceback__)
            else:
                self._run_job_success(job.id,future.result())
        self._pool.submit(run_with_times,job,run_times,self._logger.name).add_done_callback(done)
